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