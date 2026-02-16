"""HTTP Basic Auth for admin web dashboard (Phase 1).

Single shared password from ADMIN_WEB_PASSWORD env var.
Phase 2 will upgrade to JWT + per-user auth.
"""

from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from src.config import settings

security = HTTPBasic()


async def verify_admin(
    credentials: HTTPBasicCredentials = Depends(security),  # noqa: B008
) -> str:
    """FastAPI dependency — verify HTTP Basic credentials.

    Returns the username on success, raises 401 on failure.
    """
    expected = settings.security.admin_web_password
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ADMIN_WEB_PASSWORD not configured",
        )

    password_ok = secrets.compare_digest(
        credentials.password.encode("utf-8"),
        expected.encode("utf-8"),
    )
    # Accept any username for Phase 1 (single shared password)
    if not password_ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )

    return credentials.username
