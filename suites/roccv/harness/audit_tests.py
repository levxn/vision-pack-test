"""Static audits of the shipped rocCV Python tests (no GPU needed).

  audit::pytest_files_registered_in_ctest  every test_*.py under test/pybind/python is registered in the pybind ctest
  audit::pytest_value_checks               every test file compares output values, not only tensor metadata
Known (low item): 6 of 25 files are not registered in the installed ctest, and the tests check metadata only.
"""
from __future__ import annotations

import ast
import os
import re

from common import record, summary

ROOT = os.path.join(os.environ["ROCM_PATH"], "share", "roccv", "test", "pybind")
VALUE_CALLS = {"compare_array", "array_equal", "allclose", "isclose", "assert_array_equal", "assert_allclose",
               "assert_array_almost_equal", "assert_equal"}


def called_names(tree):
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            out.add(f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", ""))
    return out


def main():
    pydir = os.path.join(ROOT, "python")
    files = sorted(f for f in os.listdir(pydir) if re.match(r"test_.*\.py$", f) and f != "test_helpers.py")
    cmake = open(os.path.join(ROOT, "CMakeLists.txt"), encoding="utf-8").read()
    registered = set(re.findall(r"python/(test_\w+\.py)", cmake))
    missing = [f for f in files if f not in registered]
    record("audit", "pytest_files_registered_in_ctest", "fail" if missing else "pass",
           f"{len(missing)} of {len(files)} test files are not registered in the installed pybind ctest: {', '.join(missing)}"
           if missing else f"all {len(files)} test files registered")

    metadata_only = []
    for f in files:
        tree = ast.parse(open(os.path.join(pydir, f), encoding="utf-8").read())
        if not (called_names(tree) & VALUE_CALLS):
            metadata_only.append(f)
    record("audit", "pytest_value_checks", "fail" if metadata_only else "pass",
           f"{len(metadata_only)} of {len(files)} test files never compare output values (compare_tensors checks shape, "
           f"dtype, layout and device only): {', '.join(metadata_only)}" if metadata_only else "all files compare values")
    summary()


if __name__ == "__main__":
    main()
