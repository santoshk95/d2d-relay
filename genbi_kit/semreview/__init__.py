"""Semantic Review (item 55): a Power BI semantic model's measures checked against an organisation's KPI dictionary.

One KPI, one meaning, one value: every measure that stands for a KPI should compute it the same way, the way the
organisation defined it. The review reads a model (a .pbix, .pbit, model.bim, a Power BI project folder, or a model in
the Power BI service), reads every measure's DAX, and flags what breaks that rule.

    dax.py        DAX read: tokens, a small syntax tree, measures expanded, a canonical form (two measures that
                  compute the same thing share it) and a signature of what a formula does
    model.py      the readers: TMSL / model.bim, .pbit, PBIP folders (TMDL or model.bim), .pbix (pbix_read.py, in a
                  process of its own); one neutral model, metadata only (never the data)
    tmdl.py       the TMDL reader (Power BI projects and the Fabric definition API)
    pbix_read.py  a .pbix's model, read with PBIXRay in a separate, limited process
    kpis.py       the KPI dictionary: its fields, import (CSV, Excel, YAML, JSON), export, name matching
    analyze.py    the rules and the findings

Nothing here touches the network or the database: the web app (webapp/app/semreview.py) brings the models in and
keeps the results.
"""
