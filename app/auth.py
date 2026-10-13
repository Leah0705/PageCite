from __future__ import annotations

import os
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer()

_DEV_MODE = os.getenv("ENVIRONMENT", "local") == "local" and not os.getenv("CLERK_JWT_KEY")


@dataclass
class ClerkUser:
    user_id: str
    email: str | None = None


def _get_public_key() -> str:
    raw = os.getenv("CLERK_JWT_KEY", "").strip()
    if not raw:
        raise RuntimeError("CLERK_JWT_KEY is not configured")
    # Normalise: replace literal \n sequences (from single-line .env values)
    key = raw.replace("\\n", "\n")
    if key.startswith("-----"):
        return key
    # Fallback: base64-encoded PEM
    import base64
    return base64.b64decode(key).decode()


async def current_user(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
) -> ClerkUser:
    token = creds.credentials

    # Allow bypassing auth in local dev when no key is configured
    if _DEV_MODE:
        return ClerkUser(user_id="dev_user", email="dev@local")

    try:
        public_key = _get_public_key()
        payload = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            options={"verify_aud": False},
        )
        user_id: str = payload.get("sub", "")
        if not user_id:
            raise ValueError("JWT missing 'sub' claim")
        email: str | None = payload.get("email")
        return ClerkUser(user_id=user_id, email=email)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
        )
