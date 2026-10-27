"""Placeholder test: the package imports."""

import importlib


def test_package_imports() -> None:
    assert importlib.import_module("rtl2d_l3").__doc__
