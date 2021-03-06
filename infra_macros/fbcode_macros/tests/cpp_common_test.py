# Copyright 2016-present, Facebook, Inc.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree. An additional grant
# of patent rights can be found in the PATENTS file in the same directory.

from __future__ import absolute_import, division, print_function, unicode_literals

import tests.utils
from tests.utils import dedent


class CppCommonTest(tests.utils.TestCase):
    includes = [("@fbcode_macros//build_defs:cpp_common.bzl", "cpp_common")]

    @tests.utils.with_project()
    def test_default_headers_library_works(self, root):
        buckfile = "subdir/BUCK"
        root.addFile(
            buckfile,
            dedent(
                """
        load("@fbcode_macros//build_defs:cpp_common.bzl", "cpp_common")
        cpp_common.default_headers_library()
        cpp_common.default_headers_library()
        """
            ),
        )

        files = [
            "subdir/foo.cpp",
            "subdir/foo.h",
            "subdir/foo.hh",
            "subdir/foo.tcc",
            "subdir/foo.hpp",
            "subdir/foo.cuh",
            "subdir/foo/bar.cpp",
            "subdir/foo/bar.h",
            "subdir/foo/bar.hh",
            "subdir/foo/bar.tcc",
            "subdir/foo/bar.hpp",
            "subdir/foo/bar.cuh",
        ]
        for file in files:
            root.addFile(file, "")

        expected = {
            buckfile: dedent(
                r"""
                cxx_library(
                  name = "__default_headers__",
                  default_platform = "default-gcc",
                  defaults = {
                    "platform": "default-gcc",
                  },
                  exported_headers = [
                    "foo.cuh",
                    "foo.h",
                    "foo.hh",
                    "foo.hpp",
                    "foo.tcc",
                    "foo/bar.cuh",
                    "foo/bar.h",
                    "foo/bar.hh",
                    "foo/bar.hpp",
                    "foo/bar.tcc",
                  ],
                  labels = [
                    "is_fully_translated",
                  ],
                )
                """
            )
        }

        self.validateAudit(expected, root.runAudit([buckfile]))

    @tests.utils.with_project()
    def test_is_cpp_source(self, root):
        self.assertSuccess(
            root.runUnitTests(
                self.includes,
                [
                    'cpp_common.is_cpp_source("foo.cpp")',
                    'cpp_common.is_cpp_source("foo.cc")',
                    'cpp_common.is_cpp_source("foo.c")',
                    'cpp_common.is_cpp_source("foo.h")',
                ],
            ),
            True,
            True,
            False,
            False,
        )

    @tests.utils.with_project()
    def test_exclude_from_auto_pch(self, root):
        root.project.cells["fbcode_macros"].addFile(
            "build_defs/auto_pch_blacklist.bzl",
            dedent(
                """
                load("@bazel_skylib//lib:new_sets.bzl", "sets")
                auto_pch_blacklist = sets.make(["exclude", "exclude2/subdir"])
                """
            ),
        )
        commands = [
            'cpp_common.exclude_from_auto_pch("//test", "path")',
            'cpp_common.exclude_from_auto_pch("test//test", "path")',
            'cpp_common.exclude_from_auto_pch("//exclude2", "path")',
            'cpp_common.exclude_from_auto_pch("exclude2//exclude2", "path")',
            'cpp_common.exclude_from_auto_pch("//exclude", "path")',
            'cpp_common.exclude_from_auto_pch("exclude//exclude", "path")',
            'cpp_common.exclude_from_auto_pch("//exclude/dir1", "path")',
            'cpp_common.exclude_from_auto_pch("exclude//exclude/dir1", "path")',
            'cpp_common.exclude_from_auto_pch("//exclude/dir1/dir2", "path")',
            'cpp_common.exclude_from_auto_pch("exclude//exclude/dir1/dir2", "path")',
            'cpp_common.exclude_from_auto_pch("//exclude2/subdir", "path")',
            'cpp_common.exclude_from_auto_pch("exclude2//exclude2/subdir", "path")',
            'cpp_common.exclude_from_auto_pch("//exclude2/subdir/dir2", "path")',
            'cpp_common.exclude_from_auto_pch("exclude2//exclude2/subdir/dir2", "path")',
        ]

        expected = [
            False,
            False,
            False,
            False,
            True,
            True,
            True,
            True,
            True,
            True,
            True,
            True,
            True,
            True,
        ]

        self.assertSuccess(root.runUnitTests(self.includes, commands), *expected)

    @tests.utils.with_project(run_buckd=True)
    def test_get_link_style(self, root):
        commands = ["cpp_common.get_link_style()"]

        expected = ["static", "shared", "static_pic"]
        expected_tsan = ["static_pic", "shared", "static_pic"]

        root.updateBuckconfig("defaults.cxx_library", "type", "static")
        self.assertSuccess(root.runUnitTests(self.includes, commands), expected[0])
        root.updateBuckconfig("defaults.cxx_library", "type", "shared")
        self.assertSuccess(root.runUnitTests(self.includes, commands), expected[1])
        root.updateBuckconfig("defaults.cxx_library", "type", "static_pic")
        self.assertSuccess(root.runUnitTests(self.includes, commands), expected[2])

        root.updateBuckconfig("fbcode", "sanitizer", "thread")
        root.updateBuckconfig("defaults.cxx_library", "type", "static")
        self.assertSuccess(root.runUnitTests(self.includes, commands), expected_tsan[0])
        root.updateBuckconfig("defaults.cxx_library", "type", "shared")
        self.assertSuccess(root.runUnitTests(self.includes, commands), expected_tsan[1])
        root.updateBuckconfig("defaults.cxx_library", "type", "static_pic")
        self.assertSuccess(root.runUnitTests(self.includes, commands), expected_tsan[2])

    @tests.utils.with_project(run_buckd=True)
    def test_get_binary_link_deps(self, root):
        commands = [
            'cpp_common.get_binary_link_deps("foo", "bar", ["-fuse-ld=gold"], allocator="jemalloc", default_deps=True)',
            'cpp_common.get_binary_link_deps("foo", "baz", ["-fuse-ld=gold"], allocator="jemalloc", default_deps=False)',
        ]

        expected = [
            [
                self.rule_target(base_path="common/memory", name="jemalloc", repo=None),
                self.rule_target(
                    base_path="foo", name="bar-san-conf-__generated-lib__", repo=None
                ),
                self.rule_target(base_path="common/init", name="kill", repo=None),
            ],
            [
                self.rule_target(base_path="common/memory", name="jemalloc", repo=None),
                self.rule_target(
                    base_path="foo", name="baz-san-conf-__generated-lib__", repo=None
                ),
            ],
        ]

        expected_san = [
            [
                self.rule_target(
                    base_path="tools/build/sanitizers", name="asan-cpp", repo=None
                ),
                self.rule_target(
                    base_path="foo", name="bar-san-conf-__generated-lib__", repo=None
                ),
                self.rule_target(base_path="common/init", name="kill", repo=None),
            ],
            [
                self.rule_target(
                    base_path="tools/build/sanitizers", name="asan-cpp", repo=None
                ),
                self.rule_target(
                    base_path="foo", name="baz-san-conf-__generated-lib__", repo=None
                ),
            ],
        ]

        self.assertSuccess(root.runUnitTests(self.includes, commands), *expected)

        root.updateBuckconfig("fbcode", "global_compiler", "clang")
        root.updateBuckconfig("fbcode", "sanitizer", "address")
        self.assertSuccess(root.runUnitTests(self.includes, commands), *expected_san)
