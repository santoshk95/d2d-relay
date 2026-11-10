"""The secrets store: LLM keys, warehouse tokens, email credentials (platform plan, phase 0).

Never in the repo, the image or project.json. One encrypted file (Fernet: AES-128-CBC + HMAC-SHA256) in the state
volume; the key comes from, in order: the D2D_SECRET_KEY environment variable, a Docker secret
(/run/secrets/d2d_key), or a key file created on first use in the state volume (fine for one machine; use a Docker
secret or a vault when the platform is deployed for an organisation). Values never leave through the API —
callers inside the app read them; the admin API lists names only.
"""
import base64
import hashlib
import json
import os
import threading
import time
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from . import db

DOCKER_SECRET = Path(os.environ.get("D2D_SECRET_KEY_FILE", "/run/secrets/d2d_key"))
_lock = threading.Lock()


def _paths() -> tuple[Path, Path]:
    """(the current tenant's encrypted file, the install's key file). P17: every tenant has its own file — the
    platform's is the one it always was; one key for the install (a dedicated client install is re-keyed on export)."""
    t = db.tenant()
    store = db.STATE / "secrets.enc" if t == db.PLATFORM else db.STATE / "tenants" / t / "secrets.enc"
    return store, db.STATE / "secret.key"


def key_source() -> str:
    if os.environ.get("D2D_SECRET_KEY"):
        return "environment"
    if DOCKER_SECRET.exists():
        return "docker secret"
    return "key file in the state volume"


def _key(text: str) -> Fernet:
    """A Fernet key as given, or any other passphrase turned into one (SHA-256), e.g. a Kubernetes secret value."""
    try:
        return Fernet(text.encode())
    except ValueError:
        return Fernet(base64.urlsafe_b64encode(hashlib.sha256(text.encode()).digest()))


def _fernet() -> Fernet:
    env = os.environ.get("D2D_SECRET_KEY")
    if env:
        return _key(env.strip())
    if DOCKER_SECRET.exists():
        return _key(DOCKER_SECRET.read_text().strip())
    _, keyfile = _paths()
    if not keyfile.exists():
        keyfile.parent.mkdir(parents=True, exist_ok=True)
        keyfile.write_bytes(Fernet.generate_key())
        os.chmod(keyfile, 0o600)
    return Fernet(keyfile.read_bytes().strip())


def _load() -> dict:
    store, _ = _paths()
    if not store.exists():
        return {}
    try:
        return json.loads(_fernet().decrypt(store.read_bytes()))
    except InvalidToken as e:
        raise RuntimeError("The secrets store cannot be opened with the current key.") from e


def _save(data: dict) -> None:
    store, _ = _paths()
    store.parent.mkdir(parents=True, exist_ok=True)
    tmp = store.with_suffix(".tmp")
    tmp.write_bytes(_fernet().encrypt(json.dumps(data).encode()))
    os.chmod(tmp, 0o600)
    tmp.replace(store)


def put(scope: str, name: str, value: str, who: str | None = None) -> None:
    """scope: 'org', 'team:<id>' or 'user:<id>'; name: e.g. 'anthropic_api_key', 'snowflake_refresh_token'."""
    with _lock:
        data = _load()
        data[f"{scope}/{name}"] = {"value": value, "updated": time.time()}
        _save(data)
    db.audit("secret.put", f"{scope}/{name}", None, who)


def get(scope: str, name: str) -> str | None:
    with _lock:
        item = _load().get(f"{scope}/{name}")
    return item["value"] if item else None


def delete(scope: str, name: str, who: str | None = None) -> bool:
    with _lock:
        data = _load()
        found = data.pop(f"{scope}/{name}", None) is not None
        if found:
            _save(data)
    if found:
        db.audit("secret.delete", f"{scope}/{name}", None, who)
    return found


def names() -> list[dict]:
    """What is stored — names and dates only, never values."""
    with _lock:
        data = _load()
    return [{"scope": k.split("/", 1)[0], "name": k.split("/", 1)[1], "updated": v["updated"]} for k, v in sorted(data.items())]
