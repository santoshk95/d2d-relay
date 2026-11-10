"""Gen BI toolkit: everything the Claude agent (and the web app) needs to turn CSVs into a Power BI
project — data profiling, a DuckDB SQL view of the data, report-definition validation, the HTML
prototype renderer, the PBIP builder and the visual factory. The `genbi` command line wraps it (see cli.py)."""
import json
import os
from contextvars import ContextVar
from pathlib import Path

KIT = Path(__file__).resolve().parent
_PROJECT: ContextVar[Path | None] = ContextVar("genbi_project", default=None)


def visuals_dir() -> Path:
    """Folder with catalog.json, the .pbiviz packages and prototype/ (the browser bundle)."""
    return Path(os.environ.get("GENBI_VISUALS", KIT.parent / "custom_visuals"))


_library_resolver = None


def set_library_resolver(fn) -> None:
    """The web app's hook (P17): fn(base) -> the visual library of the tenant a request or job works in."""
    global _library_resolver
    _library_resolver = fn


def library_dir() -> Path:
    """The visual library: custom visuals built for earlier reports (one folder each), shared by every project of a
    tenant (the web app resolves the current tenant's; an agent run gets its tenant's through GENBI_LIBRARY)."""
    base = Path(os.environ.get("GENBI_LIBRARY", KIT.parent / "visual-library"))
    return _library_resolver(base) if _library_resolver else base


def use_project(path) -> None:
    """Make a project's own custom visuals (visuals/dist/*.pbiviz, from `genbi visual build`) part of the catalog,
    the prototype and the PBIP. The CLI uses its working folder; the web app sets it for each job."""
    _PROJECT.set(Path(path).resolve() if path else None)


def project_dir() -> Path | None:
    return _PROJECT.get()


def catalog() -> dict:
    """Every visual the toolkit can place: the 8 Relay visuals, the 13 Visual Atlas families, the visual library, the
    project's own custom visuals and Power BI's own visuals (`pbi.<visualType>`, family "powerbi")."""
    from . import atlas, stock
    own = json.loads((visuals_dir() / "catalog.json").read_text(encoding="utf-8"))
    return {**own, **{name: e for name, e in atlas.catalog().items() if name not in own}, **stock.catalog()}
