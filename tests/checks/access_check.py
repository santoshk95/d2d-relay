"""Cloudflare Access token check of the admin portal (app/portal.py), with a key made here standing in for
Cloudflare's: run inside the admin container (it has PyJWT and cryptography). No network is used."""
import time

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from app import portal

key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
other = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class FakeJwks:
    def __init__(self, k):
        self.k = k

    def get_signing_key_from_jwt(self, token):
        return type("K", (), {"key": self.k.public_key()})()


portal.ACCESS_TEAM, portal.ACCESS_AUD = "pasdacs-test.cloudflareaccess.com", "aud-123"
portal._jwks = FakeJwks(key)
now = int(time.time())
base = {"aud": ["aud-123"], "iss": "https://pasdacs-test.cloudflareaccess.com", "iat": now, "exp": now + 600, "email": "ops@pasdacs.com"}


def token(claims=None, signer=key):
    return jwt.encode({**base, **(claims or {})}, signer, algorithm="RS256")


cases = [
    ("from this PC (no Cloudflare header): passes", {}, None, True),
    ("through Cloudflare, no token: refused", {"cf-connecting-ip": "1.2.3.4"}, None, False),
    ("a valid Access token for a PASDACS address: passes", {"cf-connecting-ip": "1.2.3.4", "cf-access-jwt-assertion": token()}, None, True),
    ("... in the CF_Authorization cookie instead: passes", {"cf-connecting-ip": "1.2.3.4"}, {"CF_Authorization": token()}, True),
    ("another application's token (aud): refused", {"cf-connecting-ip": "1.2.3.4", "cf-access-jwt-assertion": token({"aud": ["x"]})}, None, False),
    ("another team's token (iss): refused", {"cf-connecting-ip": "1.2.3.4", "cf-access-jwt-assertion": token({"iss": "https://evil.cloudflareaccess.com"})}, None, False),
    ("an expired token: refused", {"cf-connecting-ip": "1.2.3.4", "cf-access-jwt-assertion": token({"exp": now - 3600, "iat": now - 7200})}, None, False),
    ("a token signed with another key: refused", {"cf-connecting-ip": "1.2.3.4", "cf-access-jwt-assertion": token(signer=other)}, None, False),
    ("a valid token for a non-PASDACS address: refused", {"cf-connecting-ip": "1.2.3.4", "cf-access-jwt-assertion": token({"email": "x@acme.com"})}, None, False),
]
bad = 0
for name, headers, cookies, ok in cases:
    why = portal.access_refusal(headers, cookies or {})
    good = (why is None) == ok
    bad += not good
    print(("PASS " if good else "FAIL ") + "access: " + name + ("" if good else f"   -> {why}"))
portal.ACCESS_TEAM = portal.ACCESS_AUD = ""
why = portal.access_refusal({"cf-connecting-ip": "1.2.3.4", "cf-access-jwt-assertion": token()}, {})
good = why is not None and "not set up" in why
bad += not good
print(("PASS " if good else "FAIL ") + "access: not set up, even a valid token is refused (fail closed)" + ("" if good else f"   -> {why}"))
print(f"{len(cases) + 1 - bad} of {len(cases) + 1} access checks passed")
raise SystemExit(bad)
