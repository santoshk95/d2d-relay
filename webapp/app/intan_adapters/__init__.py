"""Integration analytics discovery adapters (build-plan v2, P13): one read-only module per platform shape, each
following what the vendor's public API or catalogue exposes. `ADAPTERS` is what the source editor offers; every
adapter has a simulator in tests/mocklab/intan_sims.py and the Sample estate adapter needs no server at all."""
from __future__ import annotations

from . import (aa, adf, airflow, apigw, blueprism, boomi, cpi, glue, logicapps, logs, mail, mulesoft, n8n, oic, powerautomate, sample,
               sftp, ssis, uipath)

ADAPTERS = {m.KIND: m for m in (sample, oic, ssis, adf, airflow, cpi, mulesoft, boomi, logicapps, glue, n8n, powerautomate, uipath, blueprism, aa, apigw, sftp, mail, logs)}


def get(kind: str):
    m = ADAPTERS.get(kind)
    if not m:
        raise KeyError(kind)
    return m


def describe() -> list[dict]:
    """What the source editor shows: kinds, labels, how they sign in, their settings and credential names."""
    return [{"kind": m.KIND, "label": m.LABEL, "group": m.GROUP, "auth": m.AUTH, "docs": m.DOCS, "config": m.CONFIG, "secrets": m.SECRETS} for m in ADAPTERS.values()]
