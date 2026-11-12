import os, re, sys
os.environ.update({"D2D_AUTH": "otp", "D2D_PORTAL": sys.argv[1], "D2D_STATE": "/tmp/state", "WORKSPACES": "/tmp/projects",
                   "D2D_BACKUPS": "/tmp/backups", "GENBI_LIBRARY": "/tmp/library"})
for d in ("/tmp/state", "/tmp/projects", "/tmp/backups", "/tmp/library"):
    os.makedirs(d, exist_ok=True)
sys.path[:0] = ["/srv", "/opt/genbi"]
from app import main, edition, portal  # noqa
from fastapi.routing import APIRoute
rows = []
for r in main.app.routes:
    if not isinstance(r, APIRoute):
        continue
    path = r.path
    sample = re.sub(r"\{[^}]+\}", "x1", path)
    for m in sorted(r.methods - {"HEAD"}):
        if path.startswith("/api/"):
            if edition.blocked(sample):
                state = "404-edition"
            elif portal.ADMIN:
                state = "admin-ok" if portal.api_allowed(sample) else "404-portal"
            elif sample.startswith("/api/admin"):
                state = "404-admin"
            else:
                state = "OPEN"
        else:
            state = "nonapi"
        rows.append((state, m, path, r.endpoint.__module__ + "." + r.endpoint.__name__))
for s in sorted(set(x[0] for x in rows)):
    print(s, sum(1 for x in rows if x[0] == s))
for x in sorted(rows):
    if x[0] in ("OPEN", "nonapi", "admin-ok"):
        print("\t".join(x))
