"""VAPID key management for Web Push notifications.

Generates and persists VAPID EC P-256 key pairs. Keys are stored in
``~/.codeplane/vapid.json`` and reused across restarts so existing push
subscriptions remain valid.
"""

from __future__ import annotations

import json
from pathlib import Path

import structlog

log = structlog.get_logger()


def get_or_create_vapid_keys(codeplane_dir: Path) -> dict[str, str]:
    """Return ``{public_key, private_key}`` — generate if not present."""
    vapid_path = codeplane_dir / "vapid.json"

    if vapid_path.exists():
        try:
            data = json.loads(vapid_path.read_text())
            if data.get("public_key") and data.get("private_key"):
                return data
        except (json.JSONDecodeError, KeyError):
            log.warning("vapid_keys_corrupt_regenerating", path=str(vapid_path))

    from py_vapid import Vapid

    vapid = Vapid()
    vapid.generate_keys()
    raw_private = vapid.private_pem()
    raw_public = vapid.public_key

    # Application server key is the raw uncompressed point encoded as URL-safe base64
    import base64

    public_key_urlsafe = base64.urlsafe_b64encode(raw_public.public_bytes_raw()).decode().rstrip("=")
    private_key_urlsafe = base64.urlsafe_b64encode(
        raw_private if isinstance(raw_private, bytes) else raw_private.encode()
    ).decode().rstrip("=")

    # For pywebpush we need the PEM or raw keys
    keys = {
        "public_key": public_key_urlsafe,
        "private_key": private_key_urlsafe,
    }
    vapid_path.parent.mkdir(parents=True, exist_ok=True)
    vapid_path.write_text(json.dumps(keys, indent=2))
    vapid_path.chmod(0o600)
    log.info("vapid_keys_generated", path=str(vapid_path))
    return keys
