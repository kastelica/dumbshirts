import re
import os
import base64
import json
import time
from typing import Optional, Sequence, Dict, Any

try:
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Mail, Email, To, Content
except Exception:
    SendGridAPIClient = None

try:
    import jwt
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
except Exception:
    jwt = None


def slugify(value: str) -> str:
	value = value.strip().lower()
	# replace non-alphanumeric with hyphens
	value = re.sub(r"[^a-z0-9]+", "-", value)
	# collapse multiple hyphens
	value = re.sub(r"-+", "-", value)
	return value.strip("-")


def normalize_trend_term(term: str) -> str:
	"""Create a normalized key for trends (lowercase, alnum/space, max 5 words)."""
	if not term:
		return ""
	text = term.strip().lower()
	# allow letters/numbers/spaces only
	text = re.sub(r"[^a-z0-9\s]", "", text)
	# collapse whitespace
	text = re.sub(r"\s+", " ", text).strip()
	# limit to first 5 words
	parts = text.split(" ")
	limited = " ".join(parts[:5])
	return limited


def send_email_via_sendgrid(to_email: str, subject: str, html_body: str, *, from_email: Optional[str] = None, from_name: Optional[str] = None) -> tuple[bool, str]:
    """Send an email using SendGrid. Returns (ok, message).

    Requires SENDGRID_API_KEY in config/env. Default sender is
    email@roastcotton.com unless overridden.
    Default from_name is "Roast Cotton" unless overridden.
    """
    try:
        api_key = os.getenv("SENDGRID_API_KEY", "").strip()
        if not api_key or SendGridAPIClient is None:
            return False, "SendGrid not configured"
        sender_email = (from_email or os.getenv("EMAIL_SENDER", "email@roastcotton.com")).strip()
        sender_name = (from_name or os.getenv("EMAIL_SENDER_NAME", "Roast Cotton")).strip()
        msg = Mail(
            from_email=Email(sender_email, sender_name),
            to_emails=[To(to_email)],
            subject=subject,
            html_content=Content("text/html", html_body or "")
        )
        sg = SendGridAPIClient(api_key)
        resp = sg.send(msg)
        return (200 <= (resp.status_code or 500) < 300), f"status={resp.status_code}"
    except Exception as e:
        return False, str(e)


def render_simple_email(title: str, body_lines: Sequence[str]) -> str:
    """Very simple dark email HTML renderer suitable for transactional notices."""
    safe_lines = [str(x) for x in (body_lines or [])]
    inner = "".join([f"<p style='margin:8px 0'>{l}</p>" for l in safe_lines])
    return (
        "<div style='background:#0b0b0b;color:#e5e7eb;padding:20px;font-family:Inter,Arial,sans-serif'>"
        f"<h2 style='margin:0 0 12px 0'>{title}</h2>"
        f"{inner}"
        "<p style='margin-top:16px;font-size:12px;color:#9ca3af'>Roast Cotton</p>"
        "</div>"
    )


def get_google_public_key() -> Optional[str]:
    """Get the Google public key for JWT validation."""
    return """-----BEGIN PUBLIC KEY-----
MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAERUlUpxshr67EO66ZTX0Fpog0LEHc
nUnlSsIrOfroxTLu2XnigBK/lfYRxzQWq9K6nqsSjjYeea0T12r+y3nvqg==
-----END PUBLIC KEY-----"""


def validate_google_jwt_token(token: str, merchant_id: str) -> Optional[Dict[str, Any]]:
    """Validate Google Shopping automated discount JWT token.
    
    Args:
        token: Base64URL encoded JWT token from pv2 parameter
        merchant_id: Expected merchant ID to validate against
        
    Returns:
        Dict with token payload if valid, None if invalid
    """
    if not jwt:
        return None
        
    try:
        # Get Google's public key
        public_key_pem = get_google_public_key()
        if not public_key_pem:
            return None
            
        # Load the public key
        public_key = serialization.load_pem_public_key(public_key_pem.encode())
        
        # Decode and verify the JWT token
        payload = jwt.decode(
            token,
            public_key,
            algorithms=['ES256'],
            options={'verify_exp': True}
        )
        
        # Validate required fields
        if not all(key in payload for key in ['exp', 'o', 'm', 'p', 'c']):
            return None
            
        # Check merchant ID matches
        if payload.get('m') != merchant_id:
            return None
            
        # Check if token is expired
        current_time = int(time.time())
        if payload.get('exp', 0) < current_time:
            return None
            
        return payload
        
    except Exception:
        return None


def extract_google_discount_info(token_payload: Dict[str, Any]) -> Dict[str, Any]:
    """Extract discount information from validated JWT token payload.
    
    Args:
        token_payload: Validated JWT token payload
        
    Returns:
        Dict with discount information
    """
    return {
        'offer_id': token_payload.get('o', ''),
        'merchant_id': token_payload.get('m', ''),
        'discounted_price': float(token_payload.get('p', 0)),
        'prior_price': float(token_payload.get('pp', 0)),
        'currency': token_payload.get('c', 'USD'),
        'expires_at': token_payload.get('exp', 0)
    }


def is_google_discount_valid(session_discount: Dict[str, Any], product_id: int) -> bool:
    """Check if a Google discount stored in session is still valid.
    
    Args:
        session_discount: Google discount data from session
        product_id: Product ID to validate against
        
    Returns:
        True if discount is valid, False otherwise
    """
    if not session_discount:
        return False
        
    # Check if it's for the right product
    if session_discount.get("product_id") != product_id:
        return False
        
    # Check if it hasn't expired (48 hours from when it was set)
    expires_at = session_discount.get("expires_at", 0)
    current_time = int(time.time())
    
    # Google requires 48 hours persistence, but we'll also respect the JWT expiration
    max_persistence = 48 * 60 * 60  # 48 hours in seconds
    if current_time > expires_at or (current_time - expires_at) > max_persistence:
        return False
        
    return True

