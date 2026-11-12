"""Readers that are next in line (build-plan D3). Each lists what it will read, in the tool's own terms, and refuses
to read until it is built - so the start screen can show the tool with status "next" instead of a surprise."""
from __future__ import annotations


class NotSupported(Exception):
    pass


class _Stub:
    STATUS = "next"
    TOOL = ""
    LABEL = ""
    READS: list[str] = []
    ACCEPTS = ""

    def __init__(self, root=None, **_):
        self.root = root

    def test(self) -> dict:
        raise NotSupported(f"{self.LABEL} is next: the reader will read {', '.join(self.READS[:3])} ... (not built yet).")

    def read(self, *_, **__) -> dict:
        self.test()


class MicroStrategyReader(_Stub):
    TOOL, LABEL = "microstrategy", "MicroStrategy"
    READS = ["Documents", "Dossiers", "Reports", "Cubes (Intelligent Cubes)", "Attributes", "Metrics", "Filters", "Prompts",
             "usage from Enterprise Manager"]
    ACCEPTS = "a project package (.mmp) or Object Manager exports, plus an Enterprise Manager usage export (CSV)"


class TableauReader(_Stub):
    TOOL, LABEL = "tableau", "Tableau"
    READS = ["Workbooks (.twb / .twbx)", "Views (worksheets, dashboards)", "Data sources (.tds / .tdsx)", "Calculated fields",
             "Parameters", "Flows", "usage from the Repository (workgroup database)"]
    ACCEPTS = "workbook and data source files, or a folder exported with tabcmd; usage from the Repository views (CSV)"


class SsrsReader(_Stub):
    TOOL, LABEL = "ssrs", "SSRS"
    READS = ["Reports (.rdl)", "Shared datasets (.rsd)", "Data sources (.rds)", "Subscriptions", "Report parts",
             "usage from the Execution log (ExecutionLog3)"]
    ACCEPTS = "a folder downloaded from the report server (RDL, RSD, RDS) and an ExecutionLog3 export (CSV)"


class BusinessObjectsReader(_Stub):
    TOOL, LABEL = "businessobjects", "SAP BusinessObjects"
    READS = ["Web Intelligence documents", "Universes (.unx / .unv)", "Crystal reports", "Variables", "Prompts",
             "usage from the Audit database"]
    ACCEPTS = "a BIAR / LCMBIAR file or a Promotion Management export, plus an Audit database export (CSV)"
