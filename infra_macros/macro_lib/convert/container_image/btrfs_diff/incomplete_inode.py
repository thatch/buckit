#!/usr/bin/env python3
'''
To construct our filesystem, it is convenient to have mutable classes that
track the state-in-progress.  The `IncompleteInode` hierarchy stores that
state, and knows how to apply parsed `SendStreamItems` to mutate the state.

Once the filesystem is done, we will "freeze" it into immutable, hashable,
easily comparable `Inode` objects, making it a "breeze" to validate it.

IMPORTANT: Keep these objects correctly `deepcopy`able. That is the case at
the time of writing because:
 - `Extent` is recursively immutable and customizes copy operations to
   return the original object -- this lets us correctly track clones.
 - All other attributes store plain-old-data, or POD immutable classes that
   do not care about object identity.
 - We omit InodeID -- i.e. these objects are **just** the inode's data.
   This is important because InodeID contains an InodeIDMap reference, which
   means that correctly copying IncompleteInodes that contain InodeIDs would
   require one to copy **only** at a high enough scope of the hierarchy that
   both the InodeIDMap and all the relevant IncompleteInodes are included.
   This extra risk doesn't seem worth the debuggability reward of having
   IncompleteInodes know their identity.

Future: with `deepfrozen` done, it would be simplest to merge
`IncompleteInode` with `Inode`, and just have `apply_item` return a
partly-modified copy, in the style of `NamedTuple._replace`.
'''
import stat

from typing import Dict, Optional

from .extent import Extent
from .inode import InodeOwner, InodeUtimes, S_IFMT_TO_FILE_TYPE_NAME
from .parse_dump import SendStreamItem, SendStreamItems


class IncompleteInode:
    '''
    Base class for all inode types. Inheritance is appropriate because
    different inode types have different data, different construction logic,
    and finalization logic.
    '''
    xattrs: Dict[bytes, bytes]
    # If any of these are None, the filesystem was created badly.
    # Exception: symlinks don't have permissions.
    owner: Optional[InodeOwner]
    mode: Optional[int]  # Bottom 12 bits of `st_mode`
    file_type: int  # Upper bits of `st_mode` matching `S_IFMT`
    utimes: Optional[InodeUtimes]

    def __init__(self, *, item: SendStreamItem):
        assert isinstance(item, self.INITIAL_ITEM)
        self.xattrs = {}
        self.owner = None
        self.mode = None
        self.utimes = None
        self.file_type = self.FILE_TYPE

    def apply_item(self, item: SendStreamItem) -> None:
        assert not isinstance(item, SendStreamItems.clone), 'Do .apply_clone()'
        if isinstance(item, SendStreamItems.remove_xattr):
            del self.xattrs[item.name]
        elif isinstance(item, SendStreamItems.set_xattr):
            self.xattrs[item.name] = item.data
        elif isinstance(item, SendStreamItems.chmod):
            if stat.S_IFMT(item.mode) != 0:
                raise RuntimeError(
                    f'{item} cannot change file type bits of {self}'
                )
            self.mode = item.mode
        elif isinstance(item, SendStreamItems.chown):
            self.owner = InodeOwner(uid=item.uid, gid=item.gid)
        elif isinstance(item, SendStreamItems.utimes):
            self.utimes = InodeUtimes(
                ctime=item.ctime,
                mtime=item.mtime,
                atime=item.atime,
            )
        else:
            raise RuntimeError(f'{self} cannot apply {item}')

    def apply_clone(
        self, item: SendStreamItem, from_ino: 'IncompleteInode'
    ) -> None:
        raise RuntimeError(f'{self} cannot clone via {item} from {from_ino}')

    def _repr_fields(self):
        if self.owner is not None:
            yield f'o{self.owner}'
        if self.mode is not None:
            yield f'm{self.mode:o}'
        if self.utimes is not None:
            yield f't{self.utimes}'

    def __repr__(self):
        return '(' + ' '.join([
            S_IFMT_TO_FILE_TYPE_NAME.get(self.FILE_TYPE, self.FILE_TYPE),
            *self._repr_fields(),
        ]) + ')'


class IncompleteDir(IncompleteInode):
    FILE_TYPE = stat.S_IFDIR
    INITIAL_ITEM = SendStreamItems.mkdir


class IncompleteFile(IncompleteInode):
    extent: Extent

    FILE_TYPE = stat.S_IFREG
    INITIAL_ITEM = SendStreamItems.mkfile

    def __init__(self, *, item: SendStreamItem):
        super().__init__(item=item)
        self.extent = Extent.empty()

    def apply_item(self, item: SendStreamItem) -> None:
        if isinstance(item, SendStreamItems.truncate):
            self.extent = self.extent.truncate(length=item.size)
        elif isinstance(item, SendStreamItems.write):
            self.extent = self.extent.write(
                offset=item.offset, length=len(item.data),
            )
        elif isinstance(item, SendStreamItems.update_extent):
            self.extent = self.extent.write(
                offset=item.offset, length=item.len,
            )
        else:
            super().apply_item(item=item)

    def apply_clone(
        self, item: SendStreamItems.clone, from_ino: IncompleteInode,
    ) -> None:
        assert isinstance(item, SendStreamItems.clone)
        if not isinstance(from_ino, IncompleteFile):
            raise RuntimeError(f'Cannot {item} from {from_ino}')
        # The validation isn't required in the sense that `Extent.clone` is
        # meant to handle any input appropriately, but it's probably a
        # symptom of incorrect usage, so let's report a more useful error.
        if not (
            0 <= item.clone_offset < from_ino.extent.length and
            0 < (item.clone_offset + item.len) <= from_ino.extent.length
        ):
            raise RuntimeError(f'Bad offset/len {item} to clone {from_ino}')
        self.extent = self.extent.clone(
            to_offset=item.offset,
            from_extent=from_ino.extent,
            from_offset=item.clone_offset,
            length=item.len,
        )

    def _repr_fields(self):
        yield from super()._repr_fields()
        if self.extent.length:
            yield f'{self.extent}'


class IncompleteSocket(IncompleteInode):
    FILE_TYPE = stat.S_IFSOCK
    INITIAL_ITEM = SendStreamItems.mksock


class IncompleteFifo(IncompleteInode):
    FILE_TYPE = stat.S_IFIFO
    INITIAL_ITEM = SendStreamItems.mkfifo


class IncompleteDevice(IncompleteInode):
    dev: int

    INITIAL_ITEM = SendStreamItems.mknod

    def __init__(self, *, item: SendStreamItem):
        self.FILE_TYPE = stat.S_IFMT(item.mode)
        if self.FILE_TYPE not in (stat.S_IFBLK, stat.S_IFCHR):
            raise RuntimeError(f'unexpected device mode in {item}')
        super().__init__(item=item)
        # NB: At present, `btrfs send` redundantly sends a `chmod` after
        # device creation, but we've already saved the file type.
        self.mode = item.mode & ~self.FILE_TYPE
        self.dev = item.dev

    def _repr_fields(self):
        yield from super()._repr_fields()
        yield f'{hex(self.dev)[2:]}'


class IncompleteSymlink(IncompleteInode):
    dest: bytes

    FILE_TYPE = stat.S_IFLNK
    INITIAL_ITEM = SendStreamItems.symlink

    def __init__(self, *, item: SendStreamItem):
        super().__init__(item=item)
        self.dest = item.dest

    def apply_item(self, item: SendStreamItem) -> None:
        if isinstance(item, SendStreamItems.chmod):
            raise RuntimeError(f'{item} cannot chmod symlink {self}')
        else:
            super().apply_item(item=item)

    def _repr_fields(self):
        yield from super()._repr_fields()
        yield f'{self.dest.decode(errors="surrogateescape")}'
