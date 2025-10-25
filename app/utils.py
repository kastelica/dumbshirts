import re
import os
from typing import Optional, Sequence

try:
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Mail, Email, To, Content
except Exception:
    SendGridAPIClient = None


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


def send_email_via_sendgrid(to_email: str, subject: str, html_body: str, *, from_email: Optional[str] = None) -> tuple[bool, str]:
    """Send an email using SendGrid. Returns (ok, message).

    Requires SENDGRID_API_KEY in config/env. Default sender is
    email@dumbshirts.store unless overridden.
    """
    try:
        api_key = os.getenv("SENDGRID_API_KEY", "").strip()
        if not api_key or SendGridAPIClient is None:
            return False, "SendGrid not configured"
        sender = (from_email or os.getenv("EMAIL_SENDER", "email@dumbshirts.store")).strip()
        msg = Mail(
            from_email=Email(sender),
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
        "<p style='margin-top:16px;font-size:12px;color:#9ca3af'>Dumbshirts.store</p>"
        "</div>"
    )

