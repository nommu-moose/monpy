from __future__ import annotations

import hmac
import hashlib
from typing import Any


def verify_signature(
    *,
    secret: str,
    body: bytes | str,
    header_signature: str | None,
) -> bool:
    """
    Validate monday.com's webhook HMAC signature (if provided).

    Notes
    -----
    • monday sends an `X-Monday-Signature` header with an HMAC SHA256
      of the raw request body using your webhook signing secret.
    • This helper returns False if the header is missing.
    • Always pass the raw request body (bytes) before any decoding.
    """
    if header_signature is None:
        return False

    if isinstance(body, str):
        body = body.encode("utf-8")

    mac = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

    # Use constant-time comparison
    try:
        return hmac.compare_digest(mac, header_signature)
    except Exception:
        return False


