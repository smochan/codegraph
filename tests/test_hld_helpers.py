"""Direct unit tests for codegraph.viz.hld helpers."""
from __future__ import annotations

from codegraph.viz.hld import _is_skippable_module, _short_name


def test_short_name_simple() -> None:
    assert _short_name("pkg.module.foo") == "foo"


def test_short_name_no_dots() -> None:
    assert _short_name("foo") == "foo"


def test_short_name_empty_string() -> None:
    assert _short_name("") == ""


def test_short_name_trailing_dot() -> None:
    # rsplit on trailing dot gives empty string
    assert _short_name("pkg.module.") == ""


def test_short_name_single_segment() -> None:
    assert _short_name("alpha") == "alpha"


def test_is_skippable_module_test_dir() -> None:
    assert _is_skippable_module("pkg.tests.foo", "pkg/tests/foo.py") is True


def test_is_skippable_module_init_py() -> None:
    assert _is_skippable_module("pkg", "pkg/__init__.py") is True


def test_is_skippable_module_regular() -> None:
    assert _is_skippable_module("pkg.module", "pkg/module.py") is False


def test_is_skippable_module_test_prefix_segment() -> None:
    assert _is_skippable_module("pkg.test_utils", "pkg/test_utils.py") is True


def test_is_skippable_module_top_init() -> None:
    assert _is_skippable_module("pkg", "__init__.py") is True


def test_is_skippable_module_windows_path_init() -> None:
    assert _is_skippable_module("pkg", "pkg\\__init__.py") is True
