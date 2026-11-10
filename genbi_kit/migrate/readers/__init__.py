"""Source readers, one per BI tool, all producing the neutral model (model.py). D3 order: Cognos (exports first, then
the REST client), Qlik Sense / QlikView, then MicroStrategy, Tableau, SSRS and BusinessObjects as stubs that list
what they will read."""
from __future__ import annotations

from . import cognos, qlik, stubs

READERS = {
    "cognos": {"label": "IBM Cognos Analytics", "status": "available", "exports": cognos.CognosExports, "server": cognos.CognosRest,
               "reads": cognos.READS, "accepts": "deployment archive (.zip) or an export folder: report specifications (XML), dashboards and "
                                                 "stories (JSON), packages and data modules (JSON), content listing (CSV), Audit database export (CSV)"},
    "qlik_sense": {"label": "Qlik Sense", "status": "available", "exports": qlik.QlikSenseUnbuild, "server": None, "reads": qlik.READS_SENSE,
                   "accepts": "an app exported with `qlik app unbuild` (app-properties.json, script.qvs, sheets/, objects/, measures/, dimensions/), "
                              "or a folder of them; usage from the Monitoring apps export (CSV)"},
    "qlikview": {"label": "QlikView", "status": "available", "exports": qlik.QlikViewProject, "server": None, "reads": qlik.READS_VIEW,
                 "accepts": "a document's -prj folder (DocProperties.xml, LoadScript.txt, SH*.xml, CH*.xml), or a folder of them; usage from "
                            "the QlikView Server logs (CSV)"},
    "microstrategy": {"label": "MicroStrategy", "status": "next", "exports": stubs.MicroStrategyReader, "server": None, "reads": stubs.MicroStrategyReader.READS,
                      "accepts": stubs.MicroStrategyReader.ACCEPTS},
    "tableau": {"label": "Tableau", "status": "next", "exports": stubs.TableauReader, "server": None, "reads": stubs.TableauReader.READS,
                "accepts": stubs.TableauReader.ACCEPTS},
    "ssrs": {"label": "SSRS", "status": "next", "exports": stubs.SsrsReader, "server": None, "reads": stubs.SsrsReader.READS,
             "accepts": stubs.SsrsReader.ACCEPTS},
    "businessobjects": {"label": "SAP BusinessObjects", "status": "next", "exports": stubs.BusinessObjectsReader, "server": None,
                        "reads": stubs.BusinessObjectsReader.READS, "accepts": stubs.BusinessObjectsReader.ACCEPTS},
}


def catalogue() -> list[dict]:
    """What the start screen lists: each tool, whether its reader is available, what it reads and accepts."""
    from .. import model
    return [{"id": k, "label": v["label"], "status": v["status"], "reads": v["reads"], "accepts": v["accepts"],
             "server": v["server"] is not None, "versions": model.TOOLS.get(k, {}).get("versions", []),
             "terms": model.TOOLS.get(k, {}).get("terms", "")} for k, v in READERS.items()]
