import time
import requests
from cachetools import TTLCache
from jose import jwt, jwk
from jose.utils import base64url_decode
from fastapi import Header, HTTPException, status
from .config import settings

# cache JWKS for 1 hour
_jwks_cache = TTLCache(maxsize=1, ttl=3600)

def _get_jwks():
    if 'jwks' in _jwks_cache:
        return _jwks_cache['jwks']
    url = f"{settings.SUPABASE_URL}/auth/v1/.well-known/jwks.json"
    r = requests.get(url, timeout=5)
    r.raise_for_status()
    data = r.json()
    _jwks_cache['jwks'] = data
    return data

def verify_supabase_token(authorization: str = Header(None)) -> str:
    """
    Validates the Supabase JWT and returns the user's UUID (claims['sub']).
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Bearer token")
    token = authorization.split()[1]

    # 1) Verify signature using JWKS
    header = jwt.get_unverified_header(token)
    jwks = _get_jwks()
    key = next((k for k in jwks.get('keys', []) if k.get('kid') == header.get('kid')), None)
    if not key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token kid")

    public_key = jwk.construct(key)
    message, encoded_sig = token.rsplit('.', 1)
    decoded_sig = base64url_decode(encoded_sig.encode())
    if not public_key.verify(message.encode(), decoded_sig):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token signature")

    # 2) Validate claims (issuer + expiry)
    claims = jwt.get_unverified_claims(token)
    if claims.get("iss") != f"{settings.SUPABASE_URL}/auth/v1":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid issuer")
    if time.time() > float(claims.get("exp", 0)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")

    # 3) Return Supabase user id
    sub = claims.get("sub")
    if not sub:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No sub in token")
    return sub
