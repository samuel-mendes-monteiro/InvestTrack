"""Accounts, passwords and sessions.

Passwords: hashed with Argon2id (argon2-cffi), OWASP's first recommendation.
Each hash has its own random salt and is deliberately slow and memory-hungry,
so a stolen database is expensive to brute force. The password itself is
never stored or logged.

Sessions: an opaque random token, not a JWT. The token goes to the client;
the database keeps only its SHA-256. Logging out deletes the row, which a
JWT can't do without a list of revoked tokens. A plain SHA-256 is enough
here (unlike passwords) because the token has 256 random bits: there is
nothing to guess.
"""

import hashlib
import re
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from investtrack.models import (
    AuthSession,
    BonusCost,
    FixedIncomeRecord,
    IncomeRecord,
    OperationRecord,
    User,
)

MIN_PASSWORD = 8  # NIST SP 800-63B: at least 8, and allow long passphrases
MAX_PASSWORD = 256  # hashing has a cost: an unbounded input is a cheap attack
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class EmailTakenError(ValueError):
    pass


class InvalidCredentialsError(ValueError):
    """Wrong email or password. Deliberately doesn't say which."""


class WeakPasswordError(ValueError):
    pass


class InvalidEmailError(ValueError):
    pass


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    """SQLite drops the timezone when storing datetimes; put UTC back."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def normalize_email(email: str) -> str:
    email = email.strip().lower()
    if not EMAIL.match(email) or len(email) > 254:
        raise InvalidEmailError("invalid email")
    return email


def adopt_legacy_data(session: Session, user_id: int) -> None:
    """Give rows created before v0.5 (no owner) to this user."""
    for model in (OperationRecord, IncomeRecord, FixedIncomeRecord, BonusCost):
        session.execute(update(model).where(model.user_id.is_(None)).values(user_id=user_id))


class Auth:
    def __init__(
        self,
        hasher: PasswordHasher | None = None,
        session_days: int = 30,
        clock: Callable[[], datetime] = _utc_now,
    ):
        # Tests pass a cheap hasher; the default parameters are argon2-cffi's,
        # which follow RFC 9106's recommendations.
        self._hasher = hasher or PasswordHasher()
        self._session_days = session_days
        self._clock = clock
        # Verifying against this when the email doesn't exist makes a wrong
        # email take as long as a wrong password: response time doesn't
        # reveal which emails have an account.
        self._dummy_hash = self._hasher.hash(secrets.token_urlsafe(16))

    def register(self, session: Session, email: str, password: str) -> User:
        """Create an account. The very first one adopts the data from before v0.5."""
        email = normalize_email(email)
        if not MIN_PASSWORD <= len(password) <= MAX_PASSWORD:
            raise WeakPasswordError(
                f"password must have between {MIN_PASSWORD} and {MAX_PASSWORD} characters"
            )
        if session.scalar(select(User).where(User.email == email)):
            raise EmailTakenError("email already registered")

        first = session.scalar(select(func.count()).select_from(User)) == 0
        user = User(
            email=email, password_hash=self._hasher.hash(password), created_at=self._clock()
        )
        session.add(user)
        session.flush()  # assigns user.id
        if first:
            adopt_legacy_data(session, user.id)
        session.commit()
        return user

    def login(self, session: Session, email: str, password: str) -> tuple[str, datetime]:
        """A new session token and when it expires."""
        try:
            email = normalize_email(email)
        except InvalidEmailError:
            email = ""
        user = session.scalar(select(User).where(User.email == email)) if email else None
        try:
            self._hasher.verify(user.password_hash if user else self._dummy_hash, password)
        except (VerificationError, InvalidHashError):
            raise InvalidCredentialsError("invalid email or password") from None
        if user is None:
            raise InvalidCredentialsError("invalid email or password")

        if self._hasher.check_needs_rehash(user.password_hash):
            # Parameters got stronger since this hash was made: upgrade it now,
            # the only moment the plain password is available.
            user.password_hash = self._hasher.hash(password)

        token = secrets.token_urlsafe(32)
        now = self._clock()
        expires = now + timedelta(days=self._session_days)
        session.add(
            AuthSession(
                token_hash=hash_token(token), user_id=user.id, created_at=now, expires_at=expires
            )
        )
        session.commit()
        return token, expires

    def user_for_token(self, session: Session, token: str) -> User | None:
        record = session.get(AuthSession, hash_token(token))
        if record is None:
            return None
        if _as_utc(record.expires_at) <= self._clock():
            session.delete(record)
            session.commit()
            return None
        return session.get(User, record.user_id)

    def logout(self, session: Session, token: str) -> None:
        session.execute(delete(AuthSession).where(AuthSession.token_hash == hash_token(token)))
        session.commit()
