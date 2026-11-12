"""Test stack only (nothing is signed in): item 38 (2026-11-12), before D2D Relay is posted on social media and in ads.
- a shared link shows a picture and a description: the sign-in page's description, Open Graph and X (Twitter) tags,
  and the 1200x630 share image at /og/d2d-relay.png, open to anyone;
- /robots.txt, open to anyone (it redirected to the sign-in page);
- a ./ or ../ segment no longer walks past the sign-in check through an open folder (/fonts/../js/36-org.js gave the
  signed-in app's files to anyone), and what was open or closed before still is.
python -I -X utf8 item38_check.py <public> <admin>"""
import http.client
import os
import re
import struct
import sys
import urllib.parse

sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2]]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d2d_checks as c  # noqa: E402

P = c.BASE
check = c.check
TYPO = "—–…“”‘’·•›‹→←↔"
SHARE = "https://d2d.pasdacs.com/og/d2d-relay.png"


def get(path: str):
    """GET the path exactly as written (no ../ clean-up on the way), without following redirects."""
    u = urllib.parse.urlsplit(P)
    conn = http.client.HTTPConnection(u.hostname, u.port, timeout=60)
    try:
        conn.putrequest("GET", path, skip_accept_encoding=True)
        conn.endheaders()
        r = conn.getresponse()
        return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read()
    finally:
        conn.close()


def meta(page: str, attr: str, name: str) -> str:
    m = re.search(rf'<meta {attr}="{re.escape(name)}" content="([^"]*)"', page)
    return m.group(1) if m else ""


# ---------------------------------------------------------------- what a shared link shows
s, h, body = get("/login.html")
page = body.decode("utf-8", "replace")
head = page.split("</head>")[0]
check("share: the sign-in page opens without signing in", s == 200, s)
want = {("name", "description"): "get a Power BI file (.pbix)", ("property", "og:type"): "website",
        ("property", "og:site_name"): "D2D Relay by PASDACS", ("property", "og:url"): "https://d2d.pasdacs.com/login.html",
        ("property", "og:title"): "D2D Relay: your data to a Power BI dashboard",
        ("property", "og:description"): "with every number checked", ("property", "og:image"): SHARE,
        ("property", "og:image:width"): "1200", ("property", "og:image:height"): "630",
        ("name", "twitter:card"): "summary_large_image", ("name", "twitter:image"): SHARE}
for (attr, name), part in want.items():
    v = meta(head, attr, name)
    check(f"share: {name} says what it should", part in v, v)
check("share: og:url is the page itself, so a link preview does not loop through the / redirect",
      meta(head, "property", "og:url").endswith("/login.html"))
check("share: the sign-in page is still in plain characters", not [ch for ch in page if ch in TYPO],
      "".join(ch for ch in page if ch in TYPO)[:20])
check("share: the page title is unchanged", "<title>Sign in - D2D Relay</title>" in head)

s, h, png = get("/og/d2d-relay.png")
size = struct.unpack(">II", png[16:24]) if png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 24 else None
check("share: the share image opens without signing in, as a PNG", s == 200 and h.get("content-type") == "image/png",
      (s, h.get("content-type")))
check("share: the share image is 1200 x 630", size == (1200, 630), size)
check("share: the share image is small enough for every platform (under 1 MB)", 0 < len(png) < 1_000_000, len(png))

# ---------------------------------------------------------------- robots.txt
s, h, t = get("/robots.txt")
txt = t.decode("utf-8", "replace")
check("robots: /robots.txt opens without signing in, as plain text",
      s == 200 and h.get("content-type", "").startswith("text/plain"), (s, h.get("content-type")))
check("robots: it keeps crawlers off /api/ and /auth/ and leaves the public pages open",
      "User-agent: *" in txt and "Disallow: /api/" in txt and "Disallow: /auth/" in txt
      and not re.search(r"^Disallow: /\s*$", txt, re.M), txt)
check("robots: it is in plain characters", not [ch for ch in txt if ch in TYPO])

# ---------------------------------------------------------------- ./ and ../ segments
for path in ("/fonts/../js/36-org.js", "/icons/../js/36-org.js", "/og/../js/36-org.js", "/auth/../js/36-org.js",
             "/fonts/%2e%2e/js/36-org.js", "/fonts/%2E%2E/index.html", "/./js/36-org.js", "/fonts/../api/me",
             "/og/..", "/og/./d2d-relay.png"):
    s, h, t = get(path)
    check(f"dots: {path} is refused (404), not served", s == 404 and b"function" not in t, (s, t[:80]))
for path, code in (("/js/36-org.js", 303), ("/", 303), ("/index.html", 303), ("/.well-known/security.txt", 303),
                   ("/fonts/inter-latin-400-700.woff2", 200), ("/icons/d2d-192.png", 200), ("/terms.html", 200),
                   ("/d2d-mark.svg", 200), ("/portal.js", 200), ("/healthz", 200)):
    s, h, t = get(path)
    check(f"dots: {path} still answers {code} without signing in", s == code, s)

ok = sum(1 for _, x in c.RESULTS if x)
print(f"{ok}/{len(c.RESULTS)} checks passed")
