"""Outgoing email through an SMTP account (Gmail + App Password).

Settings come from environment variables, normally ``backend/.env``:
SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM_NAME, FRONTEND_URL.
"""

from __future__ import annotations

from email.message import EmailMessage
from email.utils import formataddr
import logging
import os
import smtplib
import ssl
from typing import Callable, Optional, Sequence, Tuple, Union


logger = logging.getLogger(__name__)


def _setting(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def is_configured() -> bool:
    return bool(_setting("SMTP_USERNAME") and _setting("SMTP_PASSWORD"))


def frontend_url() -> str:
    return _setting("FRONTEND_URL", "http://localhost:3000").rstrip("/")


def _smtp_send(message: EmailMessage) -> None:
    host = _setting("SMTP_HOST", "smtp.gmail.com")
    port = int(_setting("SMTP_PORT", "587") or 587)
    username = _setting("SMTP_USERNAME")
    password = _setting("SMTP_PASSWORD").replace(" ", "")
    context = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=context, timeout=20) as server:
            server.login(username, password)
            server.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=20) as server:
            server.starttls(context=context)
            server.login(username, password)
            server.send_message(message)


# Tests replace this to capture messages instead of sending them.
transport: Callable[[EmailMessage], None] = _smtp_send


def sender_address() -> str:
    return _setting("SMTP_USERNAME")


def build_message(
    to: Union[str, Sequence[str]],
    subject: str,
    text: str,
    html: Optional[str] = None,
    *,
    inline_image: Optional[Tuple[bytes, str]] = None,
    attachments: Sequence[Tuple[str, bytes, str]] = (),
) -> EmailMessage:
    """``inline_image`` is (jpeg bytes, content-id) shown in the HTML as
    ``cid:<content-id>``; ``attachments`` are (filename, data, mime type)."""

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr((_setting("SMTP_FROM_NAME", "VisionGuard"), sender_address()))
    message["To"] = to if isinstance(to, str) else ", ".join(to)
    message.set_content(text)
    if html:
        message.add_alternative(html, subtype="html")
        if inline_image is not None:
            data, cid = inline_image
            message.get_payload()[1].add_related(data, "image", "jpeg", cid=f"<{cid}>", filename="snapshot.jpg")
    for filename, data, mime in attachments:
        maintype, _, subtype = mime.partition("/")
        message.add_attachment(data, maintype=maintype, subtype=subtype or "octet-stream", filename=filename)
    return message


def send_email(
    to: Union[str, Sequence[str]],
    subject: str,
    text: str,
    html: Optional[str] = None,
    **extras,
) -> bool:
    """Send one email; returns False (and logs) instead of raising."""

    error = send_email_checked(to, subject, text, html, **extras)
    return error is None


def send_email_checked(
    to: Union[str, Sequence[str]],
    subject: str,
    text: str,
    html: Optional[str] = None,
    **extras,
) -> Optional[str]:
    """Like ``send_email`` but returns the error text (None when sent)."""

    if not is_configured():
        logger.warning("Email not sent: SMTP_USERNAME/SMTP_PASSWORD are not set")
        return "Gmail is not set up (SMTP_USERNAME/SMTP_PASSWORD in backend/.env)"
    try:
        transport(build_message(to, subject, text, html, **extras))
        return None
    except Exception as exc:
        logger.exception("Could not send email to %s", to)
        return f"{type(exc).__name__}: {exc}"[:500]
