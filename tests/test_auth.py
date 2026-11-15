"""Accounts, passwords and sessions."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from argon2 import PasswordHasher
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from investtrack.auth import (
    Auth,
    EmailTakenError,
    InvalidCredentialsError,
    InvalidEmailError,
    LoginThrottle,
    TooManyAttemptsError,
    WeakPasswordError,
    hash_token,
)
from investtrack.core.portfolio import AssetType, OpType
from investtrack.storage.db import init_db
from investtrack.storage.models import Asset, AuthSession, OperationRecord, User
from tests.conftest import fresh_engine

# Real Argon2id, with the cheapest parameters: tests stay fast.
FAST = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
T0 = datetime(2026, 11, 14, 12, tzinfo=UTC)


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now


@pytest.fixture
def session():
    engine = fresh_engine()
    init_db(engine)
    with Session(engine) as s:
        yield s
    engine.dispose()


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def auth(clock):
    return Auth(hasher=FAST, clock=clock)


def test_password_is_never_stored(session, auth):
    user = auth.register(session, "Ana@Example.com ", "correct horse")
    assert user.email == "ana@example.com"
    assert "correct horse" not in user.password_hash
    assert user.password_hash.startswith("$argon2id$")


def test_same_password_gets_different_hashes(session, auth):
    a = auth.register(session, "a@x.com", "same password")
    b = auth.register(session, "b@x.com", "same password")
    assert a.password_hash != b.password_hash  # each hash has its own salt


@pytest.mark.parametrize("email", ["", "ana", "ana@", "@x.com", "ana @x.com", "ana@x"])
def test_invalid_email(session, auth, email):
    with pytest.raises(InvalidEmailError):
        auth.register(session, email, "long enough")


@pytest.mark.parametrize("password", ["short", "x" * 257])
def test_password_length(session, auth, password):
    with pytest.raises(WeakPasswordError):
        auth.register(session, "ana@x.com", password)


def test_email_is_unique_ignoring_case(session, auth):
    auth.register(session, "ana@x.com", "long enough")
    with pytest.raises(EmailTakenError):
        auth.register(session, "ANA@x.com", "long enough")


def test_login_and_token(session, auth):
    user = auth.register(session, "ana@x.com", "long enough")
    token, expires = auth.login(session, "ANA@x.com", "long enough")
    assert expires == T0 + timedelta(days=30)
    assert auth.user_for_token(session, token).id == user.id
    # Only the token's hash is stored.
    stored = session.scalar(select(AuthSession))
    assert stored.token_hash == hash_token(token) != token


@pytest.mark.parametrize(
    "email, password", [("ana@x.com", "wrong password"), ("bia@x.com", "long enough"), ("x", "y")]
)
def test_wrong_credentials_give_the_same_error(session, auth, email, password):
    auth.register(session, "ana@x.com", "long enough")
    with pytest.raises(InvalidCredentialsError, match="invalid email or password"):
        auth.login(session, email, password)


def test_unknown_token(session, auth):
    assert auth.user_for_token(session, "made-up") is None


def test_session_expires(session, auth, clock):
    auth.register(session, "ana@x.com", "long enough")
    token, _ = auth.login(session, "ana@x.com", "long enough")
    clock.now = T0 + timedelta(days=30)
    assert auth.user_for_token(session, token) is None
    assert session.scalar(select(AuthSession)) is None  # expired sessions are cleaned up


def test_logout(session, auth):
    auth.register(session, "ana@x.com", "long enough")
    token, _ = auth.login(session, "ana@x.com", "long enough")
    auth.logout(session, token)
    assert auth.user_for_token(session, token) is None


def test_change_password_ends_the_other_sessions_only(session, auth):
    user = auth.register(session, "ana@x.com", "long enough")
    here, _ = auth.login(session, "ana@x.com", "long enough")
    elsewhere, _ = auth.login(session, "ana@x.com", "long enough")

    auth.change_password(session, user, here, "long enough", "a new passphrase")

    assert auth.user_for_token(session, here) == user
    assert auth.user_for_token(session, elsewhere) is None
    with pytest.raises(InvalidCredentialsError):
        auth.login(session, "ana@x.com", "long enough")
    auth.login(session, "ana@x.com", "a new passphrase")


def test_change_password_checks_the_current_one_and_the_new_length(session, auth):
    user = auth.register(session, "ana@x.com", "long enough")
    token, _ = auth.login(session, "ana@x.com", "long enough")
    with pytest.raises(InvalidCredentialsError):
        auth.change_password(session, user, token, "wrong one", "a new passphrase")
    with pytest.raises(WeakPasswordError):
        auth.change_password(session, user, token, "long enough", "short")
    assert auth.user_for_token(session, token) == user  # nothing changed
    auth.login(session, "ana@x.com", "long enough")


def test_wrong_current_passwords_are_throttled(session, auth):
    user = auth.register(session, "ana@x.com", "long enough")
    token, _ = auth.login(session, "ana@x.com", "long enough", ip="1.2.3.4")
    for _ in range(5):
        with pytest.raises(InvalidCredentialsError):
            auth.change_password(session, user, token, "wrong one", "a new one!", ip="1.2.3.4")
    with pytest.raises(TooManyAttemptsError):
        auth.change_password(session, user, token, "long enough", "a new one!", ip="1.2.3.4")


def test_delete_account_leaves_other_accounts_alone(session, auth):
    ana = auth.register(session, "ana@x.com", "long enough")
    bia = auth.register(session, "bia@x.com", "long enough")
    auth.login(session, "ana@x.com", "long enough")
    bia_token, _ = auth.login(session, "bia@x.com", "long enough")
    asset = Asset(ticker="PETR4", asset_type=AssetType.STOCK)
    session.add(asset)
    for user in (ana, bia):
        session.add(
            OperationRecord(
                user_id=user.id,
                asset=asset,
                op_type=OpType.BUY,
                date=date(2026, 1, 5),
                quantity=Decimal("1"),
                price=Decimal("10"),
                fees=Decimal("0"),
            )
        )
    session.commit()

    with pytest.raises(InvalidCredentialsError):
        auth.delete_account(session, ana, "wrong one")
    auth.delete_account(session, ana, "long enough")

    assert session.scalars(select(User.email)).all() == ["bia@x.com"]
    assert session.scalars(select(OperationRecord.user_id)).all() == [bia.id]
    assert session.scalars(select(AuthSession.user_id)).all() == [bia.id]
    assert auth.user_for_token(session, bia_token) == bia


def test_weak_old_hash_is_upgraded_on_login(session, clock):
    weak = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
    Auth(hasher=weak, clock=clock).register(session, "ana@x.com", "long enough")
    stronger = PasswordHasher(time_cost=2, memory_cost=16, parallelism=1)
    Auth(hasher=stronger, clock=clock).login(session, "ana@x.com", "long enough")
    assert "t=2" in session.scalar(select(User)).password_hash


def test_first_account_adopts_data_from_before_v05(session, auth):
    asset = Asset(ticker="PETR4", asset_type=AssetType.STOCK)
    session.add(asset)
    session.flush()
    session.add(
        OperationRecord(
            asset_id=asset.id,
            op_type=OpType.BUY,
            date=date(2026, 1, 5),
            quantity=Decimal("100"),
            price=Decimal("30"),
            fees=Decimal("0"),
        )
    )
    session.commit()

    first = auth.register(session, "ana@x.com", "long enough")
    second = auth.register(session, "bia@x.com", "long enough")
    owners = session.execute(text("SELECT user_id FROM operations")).scalars().all()
    assert owners == [first.id]
    assert second.id not in owners


# --- login throttle ----------------------------------------------------------


def fail(session, auth, times, email="ana@x.com", ip="1.1.1.1"):
    for _ in range(times):
        with pytest.raises(InvalidCredentialsError):
            auth.login(session, email, "wrong password", ip)


def test_account_is_blocked_after_five_failures_from_one_ip(session, auth, clock):
    auth.register(session, "ana@x.com", "correct horse")
    fail(session, auth, 5)
    with pytest.raises(TooManyAttemptsError) as exc:
        auth.login(session, "ana@x.com", "correct horse", "1.1.1.1")  # even the right one
    assert exc.value.retry_after == 15 * 60

    # Someone else's typos don't lock Ana out of her own machine.
    auth.login(session, "ana@x.com", "correct horse", "2.2.2.2")

    clock.now += timedelta(minutes=15)
    auth.login(session, "ana@x.com", "correct horse", "1.1.1.1")


def test_window_slides(session, auth, clock):
    fail(session, auth, 4)
    clock.now += timedelta(minutes=10)
    fail(session, auth, 1)
    with pytest.raises(TooManyAttemptsError) as exc:
        auth.login(session, "ana@x.com", "x", "1.1.1.1")
    assert exc.value.retry_after == 5 * 60  # when the first four expire
    clock.now += timedelta(minutes=5)
    fail(session, auth, 1)  # 2 failures in the window again: allowed


def test_success_resets_the_account_count_but_not_the_ip(session, clock):
    auth = Auth(hasher=FAST, clock=clock, throttle=LoginThrottle(per_ip=5, clock=clock))
    auth.register(session, "ana@x.com", "correct horse")
    fail(session, auth, 4)
    auth.login(session, "ANA@x.com", "correct horse", "1.1.1.1")
    fail(session, auth, 1)  # account count restarted, so not blocked
    with pytest.raises(TooManyAttemptsError):  # but the IP has 4 + 1 = 5
        auth.login(session, "bia@x.com", "anything", "1.1.1.1")


def test_one_ip_trying_many_emails_is_blocked(session, auth):
    for i in range(20):
        fail(session, auth, 1, email=f"user{i}@x.com")
    with pytest.raises(TooManyAttemptsError):
        auth.login(session, "new@x.com", "anything", "1.1.1.1")
    fail(session, auth, 1, email="new@x.com", ip="2.2.2.2")  # other IPs unaffected
