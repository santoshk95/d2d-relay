"""Module packs for the workbench (docs/workbench.md): one file per module, app/packs/<module id>.py, which calls
workbench.register(Pack(...)) when it is imported. Helpers of a pack live next to it as <module id>_*.py.

Every module in this folder is imported here, in name order, so adding a pack needs no edit to a shared file. A pack
that fails to import is logged and listed in BROKEN (GET /api/workbench/packs shows it to admins; the suites assert
none); the other packs and the app keep working."""
from __future__ import annotations

import importlib
import pkgutil
import traceback

BROKEN: dict[str, str] = {}

for _m in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name):
    if _m.name.startswith("_"):
        continue
    try:
        importlib.import_module(f"{__name__}.{_m.name}")
    except Exception as _e:  # noqa: BLE001 - one broken pack must not take the platform down
        traceback.print_exc()
        BROKEN[_m.name] = f"{_e.__class__.__name__}: {_e}"[:500]
