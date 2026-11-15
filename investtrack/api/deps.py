"""FastAPI dependencies: the database session, the logged-in user, the
data sources and the uploaded statement.

The sources live on `app.state` (set up in `create_app`), so tests can hand
the app fakes and every route still asks for them the same way.
"""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from investtrack.sources.b3_statement import MAX_FILE_SIZE
from investtrack.storage.events import EventSource
from investtrack.storage.market_data import MarketDataSource
from investtrack.storage.models import User
from investtrack.storage.prices import PriceProvider

# The session travels in a cookie the page's JavaScript can't read
# (HttpOnly), so an injected script can't steal it. SameSite=Strict keeps the
# browser from sending it on requests started by another site, which is
# what a CSRF attack needs; the app and the API share an origin, so it never
# needs to cross sites.
SESSION_COOKIE = "investtrack_session"

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def get_session(request: Request) -> Iterator[Session]:
    """One database session per request, always closed at the end."""
    with Session(request.app.state.engine) as session:
        yield session


def get_price_provider(request: Request) -> PriceProvider:
    return request.app.state.price_provider


def get_events(request: Request) -> EventSource:
    return request.app.state.events


def get_market_data(request: Request) -> MarketDataSource:
    return request.app.state.market_data


def session_token(request: Request) -> str | None:
    return request.cookies.get(SESSION_COOKIE) or None


def client_ip(request: Request) -> str:
    # Behind a reverse proxy this is the proxy's address, unless uvicorn
    # runs with --proxy-headers (it then trusts X-Forwarded-For).
    return request.client.host if request.client else ""


def get_current_user(request: Request, session: Annotated[Session, Depends(get_session)]) -> User:
    """The logged-in user, from the session cookie.

    Every endpoint with user data depends on this, so a request without a
    valid session never reaches it.
    """
    token = session_token(request)
    user = request.app.state.auth.user_for_token(session, token) if token else None
    if user is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            {"code": "NOT_AUTHENTICATED", "message": "missing, invalid or expired session"},
        )
    return user


async def statement_file(request: Request) -> bytes:
    """The uploaded file, sent as the raw request body.

    Too large a file is refused from the Content-Length header, before
    reading it: a huge upload costs nothing to refuse.
    """
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_FILE_SIZE:
        raise HTTPException(413, {"code": "FILE_TOO_LARGE", "message": "file too large"})
    data = await request.body()
    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(413, {"code": "FILE_TOO_LARGE", "message": "file too large"})
    return data


SessionDep = Annotated[Session, Depends(get_session)]
StatementDep = Annotated[bytes, Depends(statement_file)]
UserDep = Annotated[User, Depends(get_current_user)]
MarketDep = Annotated[MarketDataSource, Depends(get_market_data)]
PricesDep = Annotated[PriceProvider, Depends(get_price_provider)]
EventsDep = Annotated[EventSource, Depends(get_events)]
