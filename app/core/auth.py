import time
import requests
from cachetools import TTLCache
from jose import jwt, jwk, JWTError
from jose.utils import base64url_decode
from fastapi import Header, HTTPException, status
from .config import settings

# cache JWKS for 1 hour
_jwks_cache = TTLCache(maxsize=1, ttl=3600)

def _get_jwks():
    if "jwks" in _jwks_cache:
        return _jwks_cache["jwks"]
    url = f"{settings.SUPABASE_URL}/auth/v1/.well-known/jwks.json"
    r = requests.get(url, timeout=5)
    r.raise_for_status()
    data = r.json()
    _jwks_cache["jwks"] = data
    return data

def verify_supabase_token(authorization: str = Header(None)) -> str:
    """
    Validates the Supabase JWT and returns the user's UUID (claims['sub']).

    Supports:
    - RS256 with JWKS (new Supabase signing keys)
    - HS256 with legacy SUPABASE_JWT_SECRET (old mode)
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Bearer token",
        )

    token = authorization.split()[1]

    # Decode header and claims without verification for routing logic & debug
    try:
        header = jwt.get_unverified_header(token)
        claims = jwt.get_unverified_claims(token)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token format",
        )

    alg = header.get("alg")
    kid = header.get("kid")

    expected_iss = f"{settings.SUPABASE_URL}/auth/v1"

    # ------------------------------------------------------------------
    # 1) Try RS256 / JWKS path first (new-style Supabase signing keys)
    # ------------------------------------------------------------------
    jwks = _get_jwks()
    keys = jwks.get("keys") or []
    matched_key = None
    if kid:
        matched_key = next((k for k in keys if k.get("kid") == kid), None)

    if matched_key:
        public_key = jwk.construct(matched_key)
        message, encoded_sig = token.rsplit(".", 1)
        decoded_sig = base64url_decode(encoded_sig.encode())

        if not public_key.verify(message.encode(), decoded_sig):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token signature",
            )

        # Validate claims (issuer + expiry)
        if claims.get("iss") != expected_iss:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid issuer",
            )
        if time.time() > float(claims.get("exp", 0)):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token expired",
            )

        sub = claims.get("sub")
        if not sub:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="No sub in token",
            )
        return sub

    # ------------------------------------------------------------------
    # 2) Fallback: HS256 legacy secret (no JWKS keys, or kid mismatch)
    # ------------------------------------------------------------------
    if settings.SUPABASE_JWT_SECRET:
        try:
            verified_claims = jwt.decode(
                token,
                settings.SUPABASE_JWT_SECRET,
                algorithms=[alg or "HS256"],
                options={"verify_aud": False},
                issuer=expected_iss,
            )
        except JWTError as e:
            print("DEBUG HS256 verify error:", str(e))
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token (HS256)",
            )

        sub = verified_claims.get("sub")
        if not sub:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="No sub in token",
            )
        return sub

    # If we reach here:
    # - No matching JWKS key
    # - No SUPABASE_JWT_SECRET configured
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid token kid",
    )
