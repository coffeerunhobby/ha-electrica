"""Load integration modules standalone (no Home Assistant import)."""

from __future__ import annotations

import importlib.util
import os
import sys
import types

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PKG_DIR = os.path.join(_ROOT, "custom_components", "electrica")
_PKG = "electrica_under_test"


def load(mod_name: str):
    """Load one module from the integration without triggering its package init."""
    if _PKG not in sys.modules:
        pkg = types.ModuleType(_PKG)
        pkg.__path__ = [_PKG_DIR]
        sys.modules[_PKG] = pkg

    full = f"{_PKG}.{mod_name}"
    if full in sys.modules:
        return sys.modules[full]

    spec = importlib.util.spec_from_file_location(
        full, os.path.join(_PKG_DIR, f"{mod_name}.py")
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[full] = module
    spec.loader.exec_module(module)
    return module
