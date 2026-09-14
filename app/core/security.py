"""
BHUMI-NITI: Authentication & JWT Token Management
"""
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
import hashlib
import hmac

from app.core.config import settings

def hash_password(password: str) -> str:
    """Generate SHA256 HMAC hash for user password."""
    return hmac.new(settings.SECRET_KEY.encode('utf-8'), password.encode('utf-8'), hashlib.sha256).hexdigest()

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify plain password against stored hash."""
    return hmac.compare_digest(hash_password(plain_password), hashed_password)

def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Simple, zero-external-dependency signed token encoder for local/dev fallback."""
    import base64
    import json
    
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        
    to_encode.update({"exp": int(expire.timestamp())})
    
    header = {"alg": settings.ALGORITHM, "typ": "JWT"}
    
    encoded_header = base64.urlsafe_b64encode(json.dumps(header).encode()).decode().rstrip("=")
    encoded_payload = base64.urlsafe_b64encode(json.dumps(to_encode).encode()).decode().rstrip("=")
    
    signature_input = f"{encoded_header}.{encoded_payload}"
    signature = hmac.new(settings.SECRET_KEY.encode(), signature_input.encode(), hashlib.sha256).hexdigest()
    
    return f"{signature_input}.{signature}"

def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode and verify signed JWT token."""
    import base64
    import json
    
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
            
        signature_input = f"{parts[0]}.{parts[1]}"
        expected_sig = hmac.new(settings.SECRET_KEY.encode(), signature_input.encode(), hashlib.sha256).hexdigest()
        
        if not hmac.compare_digest(parts[2], expected_sig):
            return None
            
        padded_payload = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded_payload.encode()).decode())
        
        # Check expiry
        if payload.get("exp") and payload["exp"] < datetime.now(timezone.utc).timestamp():
            return None
            
        return payload
    except Exception:
        return None
