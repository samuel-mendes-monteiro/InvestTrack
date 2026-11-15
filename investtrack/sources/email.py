"""Sending email.

Only this module knows the email provider. The rest of the app sees a
`Mailer`: anything with a `send(Email)` method. Tests hand the app one that
keeps the messages in a list, so they never touch the network and can read
the link a message carries.

The provider is Resend, over its HTTP API rather than SMTP: free hosts
often block outgoing SMTP ports, while HTTPS always gets out.
"""

import logging
from dataclasses import dataclass
from typing import Protocol

import requests

RESEND_URL = "https://api.resend.com/emails"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Email:
    to: str
    subject: str
    text: str  # plain text: every client shows it, and spam filters like having it
    html: str


class EmailUnavailableError(Exception):
    """The message could not be handed to the provider."""


class Mailer(Protocol):
    def send(self, email: Email) -> None: ...


class ConsoleMailer:
    """Writes messages to the log instead of sending them: for development,
    where there is no provider key. The log then holds working reset links,
    so it is no choice for a real server."""

    def send(self, email: Email) -> None:
        logger.warning(
            "email not sent (no RESEND_API_KEY) to %s: %s\n%s", email.to, email.subject, email.text
        )


class ResendMailer:
    def __init__(
        self,
        api_key: str,
        sender: str,
        timeout: float = 10.0,
        session: requests.Session | None = None,
    ):
        self.sender = sender  # e.g. "InvestTrack <nao-responda@investtrack.online>"
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers["Authorization"] = f"Bearer {api_key}"

    def send(self, email: Email) -> None:
        payload = {
            "from": self.sender,
            "to": [email.to],
            "subject": email.subject,
            "text": email.text,
            "html": email.html,
        }
        try:
            response = self.session.post(RESEND_URL, json=payload, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as e:
            raise EmailUnavailableError(str(e)) from e
