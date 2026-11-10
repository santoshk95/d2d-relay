"""Apps & products adapters (W3, registry id `apps`).

What runs, in each platform's own terms — the canonical `application` (an app or a service) and `release` (a version
on its way to users):
  Power Apps         the Power Platform admin API (Entra client credentials for service.powerapps.com): canvas apps
                     with their owner, co-owners and who they are shared with, and the data they connect to; after
                     approval a new owner (modifyAppOwner) or the share with the whole organisation removed
                     (modifyPermissions).
  Google Play        the Play Developer Reporting API (user-perceived crash rate per versionCode) and the Publishing API
                     (an edit: the production track's staged release); after approval the staged rollout halted (the
                     track updated in an edit, then the edit committed). A service account's JWT grant.
  App Store Connect  API v1 with an ES256 JWT (issuer id, key id, the .p8 key): apps, their newest App Store version and
                     its phased release; after approval the phased release paused.
  Sentry             (web apps and services: React, Angular, Python, Java, Node.js; and the mobile builds' crash data)
                     projects, releases (Link cursor paging), release health (crash-free sessions per release) and the
                     issues a release brought (firstRelease). Read-only.

Mock lab stand-ins (tests/mocklab/sims/apps.py): power_apps, google_play, app_store_connect, sentry.
"""
from __future__ import annotations

import base64
import json
import re
import time

from .. import connectors
from ._systems import SysAdapter, register
from .ship_adapters import google_sign_in

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PLAY_BAD = 1.09            # Google Play's bad-behaviour threshold for the user-perceived crash rate (%)


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _os(platform: str) -> str:
    p = str(platform or "").lower()
    return "iOS" if "ios" in p or "apple" in p else "Android" if "android" in p else "web or service"


# ======================================================================================== Power Apps

class PowerApps(SysAdapter):
    kind, label, category = "power_apps", "Power Apps", "apps"
    simulator = "power_apps"
    docs = "https://learn.microsoft.com/en-us/power-platform/admin/powerapps-powershell"
    signin = ["service_account"]
    fields = [("base_url", "Power Apps API (https://api.powerapps.com)", True), ("tenant", "Entra tenant id", True), ("client_id", "App (client) id", True),
              ("environment", "Environment id (e.g. Default-<tenant id>)", True), ("authority", "Sign-in endpoint (optional: a national cloud)", False)]
    secrets = {"service_account": ["client_secret"]}
    ENTITIES = {"application": ("apps", "Canvas apps with their owners and sharing")}
    WRITABLE = {"application": {"owner": "the app's owner (someone who already has access)", "sharing": "people: remove the share with the whole organisation"}}
    API = {"api-version": "2016-11-01"}

    def sign_in(self, api):
        auth = (api.cfg.get("authority") or "https://login.microsoftonline.com").rstrip("/")
        r = api.raw("POST", f"{auth}/{api.cfg.get('tenant')}/oauth2/v2.0/token", data={"grant_type": "client_credentials", "client_id": api.cfg.get("client_id"),
                                                                                       "client_secret": api.secret("client_secret"), "scope": "https://service.powerapps.com/.default"})
        if r.status_code != 200:
            raise connectors.Reconsent(f"Entra ID refused the app's sign-in: {self.error_text(r)}")
        return {"Authorization": "Bearer " + r.json()["access_token"], "Accept": "application/json"}

    def _base(self, api) -> str:
        return f"/providers/Microsoft.PowerApps/scopes/admin/environments/{api.cfg.get('environment')}/apps"

    def _perms(self, api, aid) -> list[dict]:
        return api.get(f"{self._base(api)}/{aid}/permissions", self.API).get("value") or []

    def fetch(self, api, entity):
        if entity != "application":
            return super().fetch(api, entity)
        url, p, out = self._base(api), {**self.API, "$top": 250}, []
        for _ in range(200):
            b = api.get(url, p)
            out += b.get("value") or []
            if not b.get("nextLink"):
                break
            url, p = b["nextLink"], None
        for a in out:
            a["_perms"] = self._perms(api, a["name"])
        return out

    def canon(self, entity, r):
        if entity != "application":
            return r
        p = r.get("properties") or {}
        perms = r.get("_perms") or []
        co = next((x["properties"]["principal"].get("email") for x in perms if x["properties"].get("roleName") == "CanEdit" and x["properties"]["principal"].get("type") == "User"), None)
        everyone = any(x["properties"]["principal"].get("type") == "Tenant" for x in perms)
        refs = list((p.get("connectionReferences") or {}).values())
        return {"key": r["name"], "name": p.get("displayName"), "platform": "Power Apps", "owner": (p.get("owner") or {}).get("email"), "version": p.get("appVersion"), "status": "published",
                "modified": p.get("lastModifiedTime"), "owner_name": (p.get("owner") or {}).get("displayName"), "co_owner": co, "sharing": "organisation" if everyone else "people",
                "data": "; ".join(f"{x.get('displayName')} ({', '.join(x.get('dataSources') or [])})" for x in refs), "premium": any(x.get("apiTier") == "Premium" for x in refs),
                "users": p.get("sharedUsersCount"), "kind": "canvas app"}

    def field_problems(self, entity, field, value):
        if field == "owner" and not EMAIL.match(str(value or "")):
            return [f"{value!r} is not an e-mail address"]
        if field == "sharing" and value != "people":
            return ["Relay only removes the share with the whole organisation (sharing → people); sharing more widely is done in Power Apps"]
        return []

    def op_update(self, api, entity, key, changes, approval):
        if set(changes) - {"owner", "sharing"}:
            raise connectors.ConnectorError("Relay changes only an app's owner or removes its share with the whole organisation")
        for f, v in changes.items():
            if self.field_problems(entity, f, v):
                raise connectors.ConnectorError(self.field_problems(entity, f, v)[0])
        perms = self._perms(api, key)
        if "owner" in changes:
            new = next((x for x in perms if str(x["properties"]["principal"].get("email") or "").lower() == str(changes["owner"]).lower()
                        and x["properties"]["principal"].get("type") == "User"), None)
            if not new:
                raise connectors.ConnectorError(f"{changes['owner']} has no access to the app yet: share it with them first")
            api.json("POST", f"{self._base(api)}/{key}/modifyAppOwner", params=self.API, json={"roleForOldAppOwner": "CanView", "newAppOwner": new["properties"]["principal"]["id"]},
                     approval=approval, what=f"app {key}")
        if changes.get("sharing") == "people":
            gone = [{"id": x["name"]} for x in perms if x["properties"]["principal"].get("type") == "Tenant"]
            if gone:
                api.json("POST", f"{self._base(api)}/{key}/modifyPermissions", params=self.API, json={"delete": gone}, approval=approval, what=f"app {key}")
        return {"id": key}


# ======================================================================================== Google Play

class GooglePlay(SysAdapter):
    kind, label, category = "google_play", "Google Play", "apps"
    simulator = "google_play"
    docs = "https://developers.google.com/play/developer/reporting/reference/rest"
    signin = ["service_account"]
    fields = [("base_url", "Play Developer Reporting API (https://playdeveloperreporting.googleapis.com)", True),
              ("publisher_url", "Publishing API (https://androidpublisher.googleapis.com)", True)]
    secrets = {"service_account": ["service_account_json"]}
    ENTITIES = {"application": ("apps", "Apps on Google Play"), "release": ("tracks", "Production releases with their crash rate")}
    WRITABLE = {"release": {"rollout": "halted: stop a staged rollout"}}
    SCOPE = "https://www.googleapis.com/auth/androidpublisher https://www.googleapis.com/auth/playdeveloperreporting"

    def sign_in(self, api):
        return google_sign_in(self, api, self.SCOPE)

    def _pub(self, api, pkg) -> str:
        return f"{(api.cfg.get('publisher_url') or 'https://androidpublisher.googleapis.com').rstrip('/')}/androidpublisher/v3/applications/{pkg}/edits"

    def _apps(self, api) -> list[dict]:
        out, tok = [], None
        for _ in range(200):
            b = api.get("/v1beta1/apps:search", {"pageSize": 100, **({"pageToken": tok} if tok else {})})
            out += b.get("apps") or []
            tok = b.get("nextPageToken")
            if not tok:
                break
        return out

    def _track(self, api, pkg) -> dict:
        """The production track, read inside an edit (the Publishing API reads only through one), then the edit deleted."""
        eid = api.json("POST", self._pub(api, pkg), json={}, what=f"an edit of {pkg}")["id"]
        try:
            return api.get(f"{self._pub(api, pkg)}/{eid}/tracks/production")
        finally:
            api.request("DELETE", f"{self._pub(api, pkg)}/{eid}")

    def _crash(self, api, pkg) -> dict:
        b = api.json("POST", f"/v1beta1/apps/{pkg}/crashRateMetricSet:query", json={"timelineSpec": {"aggregationPeriod": "DAILY"}, "dimensions": ["versionCode"],
                                                                                     "metrics": ["userPerceivedCrashRate", "distinctUsers"]}, what=f"crash rate of {pkg}")
        out = {}
        for r in b.get("rows") or []:
            vc = next((str(d.get("int64Value") or d.get("stringValue")) for d in r.get("dimensions") or [] if d.get("dimension") == "versionCode"), None)
            m = {x["metric"]: float((x.get("decimalValue") or {}).get("value") or 0) for x in r.get("metrics") or []}
            if vc:
                out[vc] = m
        return out

    def fetch(self, api, entity):
        if entity == "application":
            return self._apps(api)
        if entity == "release":
            out = []
            for a in self._apps(api):
                pkg = a["packageName"]
                crash = self._crash(api, pkg)
                rels = self._track(api, pkg).get("releases") or []
                done = False
                for r in rels:
                    if r.get("status") == "completed":
                        if done:
                            continue
                        done = True
                    vc = str((r.get("versionCodes") or [""])[0])
                    out.append({**r, "_pkg": pkg, "_app": a.get("displayName"), "_vc": vc, "_crash": crash.get(vc) or {}})
            return out
        return super().fetch(api, entity)

    def canon(self, entity, r):
        if entity == "application":
            return {"key": r["packageName"], "name": r.get("displayName"), "platform": "Android", "owner": None, "version": None, "status": "published", "modified": None, "bundle": r["packageName"]}
        if entity == "release":
            st = r.get("status")
            rate = (r.get("_crash") or {}).get("userPerceivedCrashRate")
            return {"key": f"{r['_pkg']}:{r['_vc']}", "name": f"{r['_app']} {r.get('name')} ({r['_vc']})", "app": r["_pkg"], "version": r.get("name"), "track": "production",
                    "rollout": "halted" if st == "halted" else f"{round(float(r.get('userFraction') or 0) * 100)}%" if st == "inProgress" else "100%",
                    "status": {"inProgress": "rolling out", "halted": "halted", "completed": "released"}.get(st, st), "when": None, "error": None,
                    "os": "Android", "bundle": r["_pkg"], "crash_rate": round(rate * 100, 2) if rate is not None else None, "users": int((r.get("_crash") or {}).get("distinctUsers") or 0) or None,
                    "stop_as": "halted", "platform": "Google Play"}
        return r

    def field_problems(self, entity, field, value):
        if field == "rollout" and value != "halted":
            return ["Relay only halts a staged rollout; resuming or widening it is done in Play Console"]
        return []

    def op_update(self, api, entity, key, changes, approval):
        if set(changes) != {"rollout"} or changes["rollout"] != "halted":
            raise connectors.ConnectorError("Relay only halts a staged rollout on Google Play")
        pkg, vc = key.rsplit(":", 1)
        eid = api.json("POST", self._pub(api, pkg), json={}, approval=approval, what=f"an edit of {pkg}")["id"]
        tr = api.get(f"{self._pub(api, pkg)}/{eid}/tracks/production")
        rel = next((r for r in tr.get("releases") or [] if vc in [str(v) for v in r.get("versionCodes") or []]), None)
        if not rel or rel.get("status") != "inProgress":
            api.request("DELETE", f"{self._pub(api, pkg)}/{eid}")
            raise connectors.ConnectorError(f"{pkg} version {vc} is not in a staged rollout any more")
        rel["status"] = "halted"
        api.json("PUT", f"{self._pub(api, pkg)}/{eid}/tracks/production", json=tr, approval=approval, what=f"the production track of {pkg}")
        api.json("POST", f"{self._pub(api, pkg)}/{eid}:commit", json={}, approval=approval, what=f"the edit of {pkg}")
        return {"id": key, "edit": eid}


# ======================================================================================== App Store Connect

class AppStoreConnect(SysAdapter):
    kind, label, category = "app_store_connect", "App Store Connect", "apps"
    simulator = "app_store_connect"
    docs = "https://developer.apple.com/documentation/appstoreconnectapi"
    signin = ["api_key"]
    fields = [("base_url", "App Store Connect API (https://api.appstoreconnect.apple.com)", True), ("issuer_id", "Issuer id", True), ("key_id", "Key id", True)]
    secrets = {"api_key": ["private_key"]}
    ENTITIES = {"application": ("apps", "Apps in App Store Connect"), "release": ("appStoreVersions", "The newest App Store version of each app and its phased release")}
    WRITABLE = {"release": {"rollout": "paused: pause a phased release"}}

    def sign_in(self, api):
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
        try:
            key = serialization.load_pem_private_key(api.secret("private_key").encode(), password=None)
            if not isinstance(key, ec.EllipticCurvePrivateKey):
                raise ValueError("not an EC key")
        except (ValueError, TypeError) as e:
            raise connectors.Reconsent("The API key could not be read: paste the .p8 file App Store Connect gave you.") from e
        now = int(time.time())
        head = _b64u(json.dumps({"alg": "ES256", "kid": api.cfg.get("key_id"), "typ": "JWT"}, separators=(",", ":")).encode())
        body = _b64u(json.dumps({"iss": api.cfg.get("issuer_id"), "iat": now, "exp": now + 1100, "aud": "appstoreconnect-v1"}, separators=(",", ":")).encode())
        r_, s_ = decode_dss_signature(key.sign(f"{head}.{body}".encode(), ec.ECDSA(hashes.SHA256())))
        return {"Authorization": f"Bearer {head}.{body}.{_b64u(r_.to_bytes(32, 'big') + s_.to_bytes(32, 'big'))}", "Accept": "application/json"}

    def error_text(self, r):
        try:
            e = (r.json().get("errors") or [{}])[0]
            if e:
                return f"{e.get('title')} {e.get('detail') or ''}".strip()
        except (ValueError, AttributeError):
            pass
        return super().error_text(r)

    def _all(self, api, path, params=None) -> list[dict]:
        out, url, p = [], path, {"limit": 200, **(params or {})}
        for _ in range(200):
            b = api.get(url, p)
            out += b.get("data") or []
            url, p = (b.get("links") or {}).get("next"), None
            if not url:
                break
        return out

    def fetch(self, api, entity):
        if entity == "application":
            return self._all(api, "/v1/apps")
        if entity == "release":
            out = []
            for a in self._all(api, "/v1/apps"):
                vs = api.get(f"/v1/apps/{a['id']}/appStoreVersions", {"limit": 5}).get("data") or []
                if not vs:
                    continue
                v = vs[0]
                ph = api.get(f"/v1/appStoreVersions/{v['id']}/appStoreVersionPhasedRelease").get("data")
                out.append({**v, "_app": a, "_phased": ph})
            return out
        return super().fetch(api, entity)

    def canon(self, entity, r):
        at = r.get("attributes") or {}
        if entity == "application":
            return {"key": r["id"], "name": at.get("name"), "platform": "iOS", "owner": None, "version": None, "status": "published", "modified": None, "bundle": at.get("bundleId")}
        if entity == "release":
            app = r["_app"]["attributes"]
            ph = (r.get("_phased") or {}).get("attributes") or {}
            st = at.get("appStoreState")
            phs = ph.get("phasedReleaseState")
            status = ("rejected" if st in ("REJECTED", "METADATA_REJECTED") else "rolling out" if phs == "ACTIVE" else "paused" if phs == "PAUSED"
                      else "released" if st == "READY_FOR_SALE" else str(st or "").lower().replace("_", " "))
            return {"key": r["id"], "name": f"{app.get('name')} {at.get('versionString')}", "app": app.get("bundleId"), "version": at.get("versionString"), "track": "App Store",
                    "rollout": f"phased · day {ph.get('currentDayNumber')} of 7" if phs == "ACTIVE" else "paused" if phs == "PAUSED" else "100%" if st == "READY_FOR_SALE" else "",
                    "status": status, "when": at.get("createdDate"),
                    "error": "App Review rejected this version: the reasons are in App Store Connect › App Review (Resolution Center)." if status == "rejected" else None,
                    "os": "iOS", "bundle": app.get("bundleId"), "phased_id": (r.get("_phased") or {}).get("id"), "stop_as": "paused", "platform": "App Store"}
        return r

    def field_problems(self, entity, field, value):
        if field == "rollout" and value != "paused":
            return ["Relay only pauses a phased release; resuming it is done in App Store Connect"]
        return []

    def op_update(self, api, entity, key, changes, approval):
        if set(changes) != {"rollout"} or changes["rollout"] != "paused":
            raise connectors.ConnectorError("Relay only pauses a phased release on the App Store")
        ph = api.get(f"/v1/appStoreVersions/{key}/appStoreVersionPhasedRelease").get("data")
        if not ph or (ph.get("attributes") or {}).get("phasedReleaseState") != "ACTIVE":
            raise connectors.ConnectorError("this version has no active phased release any more")
        api.json("PATCH", f"/v1/appStoreVersionPhasedReleases/{ph['id']}", json={"data": {"type": "appStoreVersionPhasedReleases", "id": ph["id"],
                                                                                           "attributes": {"phasedReleaseState": "PAUSED"}}},
                 approval=approval, what=f"the phased release of version {key}")
        return {"id": key, "phased_release": ph["id"]}


# ======================================================================================== Sentry

class Sentry(SysAdapter):
    kind, label, category = "sentry", "Sentry", "apps"
    simulator = "sentry"
    docs = "https://docs.sentry.io/api/"
    can_write = False
    signin = ["token"]
    fields = [("base_url", "Sentry (https://sentry.io, or your own server)", True), ("organization", "Organisation slug", True)]
    secrets = {"token": ["token"]}
    ENTITIES = {"application": ("projects", "Projects (an app or a service each)"), "release": ("releases", "Releases with crash-free sessions and the issues they brought")}

    def sign_in(self, api):
        return {"Authorization": "Bearer " + api.secret("token"), "Accept": "application/json"}

    def error_text(self, r):
        try:
            d = r.json().get("detail")
            if isinstance(d, str):
                return d
        except (ValueError, AttributeError):
            pass
        return super().error_text(r)

    def _org(self, api) -> str:
        return f"/api/0/organizations/{api.cfg.get('organization')}"

    def _all(self, api, path, params=None) -> list:
        out, url, p = [], path, {"per_page": 100, **(params or {})}
        for _ in range(200):
            r = api.request("GET", url, params=p)
            out += self.check(r, path) or []
            m = re.search(r'<([^>]+)>;\s*rel="next";\s*results="true"', r.headers.get("Link") or "")
            if not m:
                break
            url, p = m.group(1), None
        return out

    def fetch(self, api, entity):
        if entity == "application":
            return self._all(api, f"{self._org(api)}/projects/")
        if entity == "release":
            rels = self._all(api, f"{self._org(api)}/releases/")
            health = api.get(f"{self._org(api)}/sessions/", {"field": "crash_free_rate(session)", "groupBy": ["release", "project"], "statsPeriod": "14d", "project": "-1"}).get("groups") or []
            cf = {(g["by"].get("release"), str(g["by"].get("project"))): (g.get("totals") or {}).get("crash_free_rate(session)") for g in health}
            out, newest = [], set()
            for r in sorted(rels, key=lambda x: x.get("dateCreated") or "", reverse=True):
                for p in r.get("projects") or []:
                    first = p["slug"] not in newest
                    newest.add(p["slug"])
                    iss = self._all(api, f"{self._org(api)}/issues/", {"query": f"is:unresolved firstRelease:{r['version']}"}) if first and r.get("newGroups") else []
                    iss = [i for i in iss if (i.get("project") or {}).get("slug") == p["slug"]]
                    out.append({**r, "_project": p, "_cf": cf.get((r["version"], str(p["id"]))), "_issues": iss, "_newest": first})
            return out
        return super().fetch(api, entity)

    def canon(self, entity, r):
        if entity == "application":
            return {"key": r["slug"], "name": r.get("name"), "platform": r.get("platform"), "owner": None, "version": None, "status": r.get("status"), "modified": None}
        if entity == "release":
            v = str(r["version"])
            app, _, rest = v.partition("@")
            ver = rest.split("+", 1)[0] if rest else v
            top = max(r.get("_issues") or [], key=lambda i: int(i.get("userCount") or 0), default=None)
            cf = r.get("_cf")
            return {"key": f"{r['_project']['slug']}:{v}", "name": f"{r['_project'].get('name')} {ver}", "app": app, "version": ver, "track": "Sentry release", "rollout": None,
                    "status": "newest" if r.get("_newest") else "earlier", "when": r.get("dateReleased") or r.get("dateCreated"),
                    "error": f"{top['title']} ({top.get('culprit')}) — {top.get('userCount')} users since this release" if top else None,
                    "os": _os(r["_project"].get("platform")), "bundle": app, "project": r["_project"]["slug"], "crash_free": round(cf * 100, 2) if cf is not None else None,
                    "new_issue": top.get("shortId") if top else None, "new_issue_users": int(top.get("userCount") or 0) if top else 0, "platform": "Sentry"}
        return r


ADAPTERS = [register(a) for a in (PowerApps(), GooglePlay(), AppStoreConnect(), Sentry())]
STORE_KINDS = ("google_play", "app_store_connect")
RELEASE_KINDS = ("google_play", "app_store_connect", "sentry")
