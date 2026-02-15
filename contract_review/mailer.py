import logging
import os
import re
import smtplib
from email.message import EmailMessage
from typing import Any

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"^[^@\s\r\n]+@[^@\s\r\n]+\.[^@\s\r\n]+$")


class SmtpMailer:
    def __init__(self):
        self.host = os.environ.get("SMTP_HOST", "")
        self.port = int(os.environ.get("SMTP_PORT", "25"))
        self.sender = os.environ.get("SMTP_SENDER", "noreply@contractreview.local")
        self.username = os.environ.get("SMTP_USERNAME", "")
        self.password = os.environ.get("SMTP_PASSWORD", "")
        self.starttls = os.environ.get("SMTP_STARTTLS", "false").lower() == "true"

    @property
    def enabled(self) -> bool:
        return bool(self.host)

    def send_event(self, recipient: str, event: str, payload: dict[str, Any]) -> bool:
        if not self.enabled:
            return False
        if not _EMAIL_RE.match(recipient):
            logger.warning("Invalid email recipient skipped: %s", recipient)
            return False
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = recipient
        message["Subject"] = f"[Contract Review] {event}"
        message.set_content(f"Event: {event}\n\nPayload:\n{payload}")

        with smtplib.SMTP(self.host, self.port, timeout=10) as smtp:
            if self.starttls:
                smtp.starttls()
            if self.username:
                smtp.login(self.username, self.password)
            smtp.send_message(message)
        return True
