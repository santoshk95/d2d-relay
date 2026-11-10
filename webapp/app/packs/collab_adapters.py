"""Content adapters (W3, registry id `collab`): SharePoint, OneDrive and Teams content through Microsoft Graph v1.0 (the
same app-registration sign-in as Entra ID: client credentials, scope https://graph.microsoft.com/.default) behind the
Connector SDK. Sites are the canonical `site`; the files and folders in their document libraries the canonical `item`,
each with its sharing (an anonymous link, an organisation-wide link, or members only). Writes carry X-Relay-Approval:
an anonymous link removed (DELETE …/permissions/{id}) or a folder created (POST …/children). Google Workspace and
Confluence content comes in as exports for now.

Mock lab stand-in: tests/mocklab/sims/msgraph.py (msgraph: sites, drives, items, permissions).
"""
from __future__ import annotations

from .. import connectors
from ._systems import day, register
from .iam_adapters import G, EntraID


class M365Content(EntraID):
    kind, label, category = "m365_content", "Microsoft 365 content (SharePoint, OneDrive, Teams)", "collab"
    simulator = "msgraph"
    docs = "https://learn.microsoft.com/en-us/graph/api/resources/driveitem?view=graph-rest-1.0"
    fields = EntraID.fields + [("sites", "Sites to read (names, comma-separated; empty: every site)", False)]
    ENTITIES = {"site": ("sites", "Sites"), "item": ("driveItems", "Files and folders (document libraries)")}
    CREATES = ("item",)
    WRITABLE = {"item": {"sharing": "sharing"}}
    DEACTIVATE: dict = {}
    JOBS = "—"

    def _sites(self, api) -> list[dict]:
        if "sites" not in api.state:
            want = {s.strip().lower() for s in str(api.cfg.get("sites") or "").split(",") if s.strip()}
            rows = self._all(api, f"{G}/sites", {"search": "*"})
            api.state["sites"] = [s for s in rows if not want or str(s.get("name") or "").lower() in want]
        return api.state["sites"]

    def _drives(self, api) -> list[tuple[dict, dict]]:
        if "drives" not in api.state:
            api.state["drives"] = [(s, d) for s in self._sites(api) for d in self._all(api, f"{G}/sites/{s['id']}/drives")]
        return api.state["drives"]

    def _sharing(self, api, did: str, iid: str) -> tuple[str, list[str]]:
        perms = api.get(f"{G}/drives/{did}/items/{iid}/permissions").get("value") or []
        anon = [p["id"] for p in perms if (p.get("link") or {}).get("scope") == "anonymous"]
        org = [p["id"] for p in perms if (p.get("link") or {}).get("scope") == "organization"]
        return ("anonymous link" if anon else "organisation link" if org else "members"), anon

    def fetch(self, api, entity):
        if entity == "site":
            return self._sites(api)
        if entity == "item":
            out = []
            for s, d in self._drives(api):
                for it in self._all(api, f"{G}/drives/{d['id']}/root/children"):
                    share, anon = self._sharing(api, d["id"], it["id"])
                    out.append({**it, "_site": s.get("name"), "_drive": d["id"], "_sharing": share, "_anon": anon})
            return out
        return []

    def canon(self, entity, r):
        if entity == "site":
            return {"key": r["id"], "name": r.get("name") or r.get("displayName"), "url": r.get("webUrl"), "items": None}
        if entity == "item":
            return {"key": f"{r['_drive']}/{r['id']}", "name": r.get("name"), "site": r.get("_site"), "kind": "folder" if "folder" in r else "file", "size": r.get("size"),
                    "modified": day(r.get("lastModifiedDateTime")) or None, "sharing": r.get("_sharing"), "url": r.get("webUrl")}
        return r

    def runs(self, api):
        return []

    def payload(self, entity, rec):
        if entity != "item":
            return super().payload(entity, rec)
        return {"name": rec.get("name"), "folder": {}, "@microsoft.graph.conflictBehavior": "fail", "_site": rec.get("site")}

    def problems(self, c, entity, rec):
        out = []
        if entity == "item":
            if not rec.get("name"):
                out.append("a folder needs a name")
            elif any(ch in str(rec["name"]) for ch in '"*:<>?/\\|'):
                out.append(f"“{rec['name']}” has a character SharePoint does not allow in a name")
        return out

    def op_create(self, api, entity, rec, approval):
        site = str(rec.get("_site") or "").lower()
        drives = self._drives(api)
        did = next((d["id"] for s, d in drives if not site or str(s.get("name") or "").lower() == site), None) or (drives[0][1]["id"] if drives else None)
        if not did:
            raise connectors.ConnectorError("No document library to create the folder in: check the sites on the connection.")
        body = {k: v for k, v in rec.items() if not k.startswith("_")}
        r = api.request("POST", f"{G}/drives/{did}/items/root/children", json=body, headers={"Content-Type": "application/json"}, approval=approval)
        b = self.check(r, "children", (201,))
        return {"id": f"{did}/{b.get('id')}"}

    def op_update(self, api, entity, key, changes, approval):
        did, _, iid = str(key).partition("/")
        for f, v in changes.items():
            if f != "sharing" or str(v).lower() == "anonymous link":
                raise connectors.ConnectorError("Relay only removes sharing through this connection (an anonymous link off): it never widens access")
            _, anon = self._sharing(api, did, iid)
            for pid in anon:
                r = api.request("DELETE", f"{G}/drives/{did}/items/{iid}/permissions/{pid}", approval=approval)
                self.check(r, f"permission {pid}", (204,))
        return {"id": key}


ADAPTERS = [register(M365Content())]
