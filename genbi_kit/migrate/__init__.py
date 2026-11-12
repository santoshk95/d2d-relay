"""Migrate BI (build-plan v2, P15): readers for BI estates, a tool-neutral model of what they hold, the rules that
turn it into today's report definition (definition.yaml -> PBIP builder -> review gates), rationalisation rules
with a live preview, and the proof of numbers against the source.

    model.py          the neutral model: datasets, reports, queries, calculations, filters, prompts, pages, visuals,
                      usage, owners, folders, dependencies - plain dicts, JSON on disk (estate.json)
    expr.py           the Cognos expression language parsed into a small AST (shared by the rules and the simulator)
    readers/          cognos (exports, deployment archives, REST), qlik (Qlik Sense unbuild, QlikView project
                      folders, load scripts), stubs (MicroStrategy, Tableau, SSRS, BusinessObjects: next)
    sample_estate.py  a seeded synthetic Cognos estate written as real export files, with the data behind it
    rules.py          calculation and visual mappings source -> definition schema, confidence, reasons, rule packs
    decide.py         keep / merge / retire / needs a decision with the user's rules and a live preview
    source_sim.py     a small independent engine that runs a source report's queries on the data (the proof's
                      "source" side)
    convert.py        the neutral model -> definition.yaml (rules first; gaps listed for the agent)
    proof.py          numbers vs source: the source simulator against the converted definition's prototype SQL
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
