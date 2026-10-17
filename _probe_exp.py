"""Throwaway probe: a validly-signed token WITHOUT exp must be rejected."""

import os
import sys

sys.path.insert(0, "apps/api")
os.environ["VERIPAY_DATABASE_URL"] = "sqlite:///./_probe.db"

import jwt  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.security import create_access_token, decode_access_token  # noqa: E402

settings = get_settings()

token = create_access_token(
    user_id="00000000-0000-0000-0000-000000000001",
    organization_id="00000000-0000-0000-0000-000000000002",
    role="owner",
)
print("normal token accepted:", bool(decode_access_token(token)))

raw = jwt.encode(
    {"sub": "x", "org_id": "y", "type": "access"},
    settings.jwt_secret,
    algorithm="HS256",
)
try:
    decode_access_token(raw)
    print("FAIL: exp-less token was accepted")
except jwt.PyJWTError as exc:
    print("exp-less token rejected:", type(exc).__name__)

os.remove("_probe.db")
