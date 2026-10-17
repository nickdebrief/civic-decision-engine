"""Shared verification of the existing signed administrator session.

This module deliberately verifies a presented session token; it does not issue
one.  Issuing a session remains the authenticated login concern in the admin
route module.  Keeping verification here lets private services use the same
trust boundary without importing the route module (which imports them).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

ADMIN_SESSION_SECRET_ENV = "CDE_ADMIN_SESSION_SECRET"


class AdminSessionVerificationError(ValueError):
    pass


def verify_signed_admin_session(session: Any, *, now: int | None = None) -> dict[str, Any]:
    secret = os.getenv(ADMIN_SESSION_SECRET_ENV)
    if not secret or not isinstance(session, str):
        raise AdminSessionVerificationError("admin_session_unauthorized")
    try:
        payload_b64, signature = session.split(".", 1)
        expected = base64.urlsafe_b64encode(
            hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256).digest()
        ).rstrip(b"=").decode("ascii")
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        payload = json.loads(base64.urlsafe_b64decode((payload_b64 + "=" * (-len(payload_b64) % 4)).encode("ascii")).decode("utf-8"))
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AdminSessionVerificationError("admin_session_unauthorized") from exc
    if set(payload) != {"role", "username", "issued_at", "expires_at"} or payload.get("role") != "admin":
        raise AdminSessionVerificationError("admin_session_unauthorized")
    if not isinstance(payload.get("username"), str) or not payload["username"].strip():
        raise AdminSessionVerificationError("admin_session_unauthorized")
    if not isinstance(payload.get("expires_at"), int) or payload["expires_at"] <= int(now if now is not None else time.time()):
        raise AdminSessionVerificationError("admin_session_unauthorized")
    return payload
