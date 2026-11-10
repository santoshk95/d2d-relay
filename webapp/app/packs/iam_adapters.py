"""Identity adapters (W3, registry id `iam`): Microsoft Entra ID through Microsoft Graph v1.0 (OAuth 2.0 client
credentials, scope https://graph.microsoft.com/.default) and Okta's Management API (an SSWS API token) behind the
Connector SDK. Accounts are the canonical `user` (key, name, e-mail, employee id, status, last sign-in, MFA,
department), plus `group` and, for Entra ID, `app` (app registrations with their secrets' expiry). Entra ID's app
sign-ins are its runs (an expired client secret fails them). Every write carries X-Relay-Approval: an account created
(staged in Okta), switched off or on. Google Workspace, AWS IAM and SAP roles come in as exports for now.

Mock lab stand-ins: tests/mocklab/sims/msgraph.py (msgraph) and tests/mocklab/sims/okta.py (okta).
"""
from __future__ import annotations

import re
import secrets as _secrets
import time

from .. import connectors
from ._systems import SysAdapter, day, register, when

GRAPH = "https://graph.microsoft.com"
G = "/v1.0"


class EntraID(SysAdapter):
    kind, label, category = "entra_id", "Microsoft Entra ID", "iam"
    simulator = "msgraph"
    docs = "https://learn.microsoft.com/en-us/graph/api/resources/users?view=graph-rest-1.0"
    signin = ["service_account"]
    fields = [("base_url", "Microsoft Graph (https://graph.microsoft.com)", True), ("tenant", "Entra tenant id", True), ("client_id", "App (client) id", True),
              ("authority", "Sign-in endpoint (optional: a national cloud)", False)]
    secrets = {"service_account": ["client_secret"]}
    ENTITIES = {"user": ("users", "Users"), "group": ("groups", "Groups"), "app": ("applications", "App registrations")}
    CREATES = ("user",)
    WRITABLE = {"user": {"status": "accountEnabled", "department": "department"}}
    DEACTIVATE = {"user": {"status": "disabled"}}
    JOBS = "App sign-ins"

    def sign_in(self, api):
        auth = (api.cfg.get("authority") or "https://login.microsoftonline.com").rstrip("/")
        r = api.raw("POST", f"{auth}/{api.cfg.get('tenant')}/oauth2/v2.0/token", data={"grant_type": "client_credentials", "client_id": api.cfg.get("client_id"),
                                                                                       "client_secret": api.secret("client_secret"), "scope": f"{GRAPH}/.default"})
        if r.status_code != 200:
            raise connectors.Reconsent(f"Entra ID refused the app's sign-in: {self.error_text(r)}")
        return {"Authorization": "Bearer " + r.json()["access_token"], "Accept": "application/json"}

    def error_text(self, r):
        try:
            b = r.json()
            if isinstance(b.get("error"), dict):
                return f"{b['error'].get('code')}: {b['error'].get('message')}"
            return b.get("error_description") or b.get("error") or super().error_text(r)
        except (ValueError, AttributeError):
            return super().error_text(r)

    def _all(self, api, path, params=None):
        out, url, p = [], path, params
        for _ in range(1000):
            b = api.get(url, p)
            out += b.get("value") or []
            if not b.get("@odata.nextLink"):
                return out
            url, p = b["@odata.nextLink"], None
        return out

    def _signins(self, api) -> list[dict]:
        if "signins" not in api.state:
            api.state["signins"] = self._all(api, f"{G}/auditLogs/signIns")
        return api.state["signins"]

    def fetch(self, api, entity):
        if entity == "user":
            last: dict = {}
            for s in self._signins(api):
                if s.get("userId") and (s.get("status") or {}).get("errorCode") == 0:
                    last[s["userId"]] = max(last.get(s["userId"]) or "", s["createdDateTime"])
            return [{**u, "_last": last.get(u["id"])} for u in self._all(api, f"{G}/users")]
        if entity in self.ENTITIES:
            return self._all(api, f"{G}/{self.ENTITIES[entity][0]}")
        return super().fetch(api, entity)

    def canon(self, entity, r):
        if entity == "user":
            return {"key": r["id"], "name": r.get("displayName"), "email": r.get("mail") or r.get("userPrincipalName"), "employee_id": r.get("employeeId"),
                    "status": "active" if r.get("accountEnabled") else "disabled", "last_signin": day(r.get("_last")) or None, "mfa": None, "department": r.get("department")}
        if entity == "group":
            return {"key": r["id"], "name": r.get("displayName"), "members": None}
        if entity == "app":
            ends = [c.get("endDateTime") for c in r.get("passwordCredentials") or [] if c.get("endDateTime")]
            return {"key": r["id"], "name": r.get("displayName"), "secret_expires": day(max(ends)) if ends else None, "status": "active"}
        return r

    def runs(self, api):
        out = []
        for s in self._signins(api):
            if s.get("userId"):
                continue                                       # people's sign-ins are not runs; an app's client-credential sign-ins are
            st = s.get("status") or {}
            out.append({"job": s.get("appDisplayName"), "label": s.get("appDisplayName"), "id": s.get("id"), "started": when(s.get("createdDateTime")), "ended": when(s.get("createdDateTime")),
                        "status": "failed" if st.get("errorCode") else "succeeded", "error": (f"AADSTS{st.get('errorCode')}: {st.get('failureReason')}" if st.get("errorCode") else None)})
        return sorted(out, key=lambda r: r["started"] or 0, reverse=True)

    def payload(self, entity, rec):
        if entity != "user":
            return super().payload(entity, rec)
        upn = str(rec.get("email") or "")
        first, _, last = str(rec.get("name") or "").partition(" ")
        return {"accountEnabled": False, "displayName": rec.get("name"), "givenName": first, "surname": last or None, "mailNickname": upn.split("@")[0], "userPrincipalName": upn,
                "mail": upn, "department": rec.get("department") or None, "employeeId": rec.get("employee_id") or None,
                "passwordProfile": {"forceChangePasswordNextSignIn": True, "password": "_set_at_write"}}

    def problems(self, c, entity, rec):
        out = []
        if entity == "user" and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", str(rec.get("email") or "")):
            out.append("an Entra ID account needs a user principal name (the work e-mail)")
        return out

    def op_create(self, api, entity, rec, approval):
        body = {k: v for k, v in rec.items() if not k.startswith("_")}
        body["passwordProfile"] = {"forceChangePasswordNextSignIn": True, "password": _secrets.token_urlsafe(18) + "!9a"}   # never stored, never shown: the person resets it
        r = api.request("POST", f"{G}/users", json=body, headers={"Content-Type": "application/json"}, approval=approval)
        b = self.check(r, "users", (201,))
        return {"id": b.get("id")}

    def op_update(self, api, entity, key, changes, approval):
        body = {}
        for f, v in changes.items():
            col = self.WRITABLE.get(entity, {}).get(f)
            if not col:
                raise connectors.ConnectorError(f"{f} cannot be changed on an Entra ID user through Relay")
            body[col] = (str(v).lower() not in ("disabled", "terminated", "blocked", "inactive")) if f == "status" else v
        r = api.request("PATCH", f"{G}/users/{key}", json=body, headers={"Content-Type": "application/json"}, approval=approval)
        self.check(r, f"user {key}", (204, 200))
        return {"id": key}


OKTA_STATUS = {"ACTIVE": "active", "STAGED": "staged", "PROVISIONED": "active", "RECOVERY": "active", "PASSWORD_EXPIRED": "active", "LOCKED_OUT": "locked",
               "SUSPENDED": "suspended", "DEPROVISIONED": "disabled"}
LINK_NEXT = re.compile(r'<([^>]+)>;\s*rel="next"')


class Okta(SysAdapter):
    kind, label, category = "okta", "Okta", "iam"
    simulator = "okta"
    docs = "https://developer.okta.com/docs/api/openapi/okta-management/management/tag/User/"
    signin = ["api_key"]
    fields = [("base_url", "Okta org URL (https://<org>.okta.com)", True)]
    secrets = {"api_key": ["api_token"]}
    ENTITIES = {"user": ("users", "Users"), "group": ("groups", "Groups")}
    CREATES = ("user",)
    WRITABLE = {"user": {"status": "status"}}
    DEACTIVATE = {"user": {"status": "disabled"}}
    JOBS = "System Log"

    def sign_in(self, api):
        return {"Authorization": "SSWS " + api.secret("api_token"), "Accept": "application/json"}

    def retry_after(self, r):
        reset = r.headers.get("X-Rate-Limit-Reset")             # Okta sends an epoch reset, not Retry-After
        if reset and reset.isdigit():
            return max(0.0, min(5.0, int(reset) - time.time()))
        return super().retry_after(r)

    def error_text(self, r):
        try:
            b = r.json()
            causes = "; ".join(c.get("errorSummary", "") for c in b.get("errorCauses") or [])
            return f"{b.get('errorCode')}: {b.get('errorSummary')}" + (f" ({causes})" if causes else "")
        except (ValueError, AttributeError):
            return super().error_text(r)

    def _all(self, api, path, params=None):
        """Cursor paging through the Link header's rel="next"."""
        out, url, p = [], path, {"limit": 200, **(params or {})}
        for _ in range(1000):
            r = api.request("GET", url, params=p)
            out += self.check(r, url) or []
            m = LINK_NEXT.search(r.headers.get("link") or "")
            if not m:
                return out
            url, p = m.group(1), None
        return out

    def fetch(self, api, entity):
        if entity == "user":
            rows = self._all(api, "/api/v1/users")                   # Okta leaves DEPROVISIONED users out of a plain list: ask for them too,
            seen = {u["id"] for u in rows}                            # so a switched-off account reads back as off (not as missing)
            rows += [u for u in self._all(api, "/api/v1/users", {"search": 'status eq "DEPROVISIONED"'}) if u["id"] not in seen]
            for u in rows:                                           # MFA: the user's enrolled factors
                if u.get("status") == "ACTIVE":
                    u["_factors"] = len(self.check(api.request("GET", f"/api/v1/users/{u['id']}/factors"), "factors") or [])
            return rows
        if entity == "group":
            return self._all(api, "/api/v1/groups")
        return super().fetch(api, entity)

    def canon(self, entity, r):
        if entity == "user":
            p = r.get("profile") or {}
            return {"key": r["id"], "name": f"{p.get('firstName') or ''} {p.get('lastName') or ''}".strip(), "email": p.get("email") or p.get("login"),
                    "employee_id": p.get("employeeNumber"), "status": OKTA_STATUS.get(r.get("status"), "unknown"), "last_signin": day(r.get("lastLogin")) or None,
                    "mfa": (r["_factors"] > 0) if "_factors" in r else None, "department": p.get("department"), "login": p.get("login")}
        if entity == "group":
            return {"key": r["id"], "name": (r.get("profile") or {}).get("name"), "members": None}
        return r

    def payload(self, entity, rec):
        if entity != "user":
            return super().payload(entity, rec)
        first, _, last = str(rec.get("name") or "").partition(" ")
        return {"profile": {"firstName": first, "lastName": last or first, "email": rec.get("email"), "login": rec.get("email"), "employeeNumber": rec.get("employee_id"),
                            "department": rec.get("department")}}

    def problems(self, c, entity, rec):
        if entity == "user" and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", str(rec.get("email") or "")):
            return ["an Okta user needs a login (the work e-mail)"]
        return []

    def op_create(self, api, entity, rec, approval):
        r = api.request("POST", "/api/v1/users", params={"activate": "false"}, json={k: v for k, v in rec.items() if not k.startswith("_")},
                        headers={"Content-Type": "application/json"}, approval=approval)
        b = self.check(r, "users", (200, 201))
        return {"id": b.get("id")}

    def op_update(self, api, entity, key, changes, approval):
        for f, v in changes.items():
            if f != "status":
                raise connectors.ConnectorError(f"{f} cannot be changed on an Okta user through Relay")
            action = "deactivate" if str(v).lower() in ("disabled", "terminated", "blocked", "inactive", "deprovisioned") else "activate"
            r = api.request("POST", f"/api/v1/users/{key}/lifecycle/{action}", headers={"Content-Type": "application/json"}, approval=approval)
            self.check(r, f"user {key} {action}", (200, 204))
        return {"id": key}


ADAPTERS = [register(a) for a in (EntraID(), Okta())]
