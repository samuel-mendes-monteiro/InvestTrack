"""Accounts and sessions: register, log in and out, password, deletion."""

from fastapi import APIRouter, Request, Response, status

from investtrack.api.deps import SESSION_COOKIE, SessionDep, UserDep, client_ip, session_token
from investtrack.api.errors import api_error
from investtrack.api.schemas import (
    AccountDeletion,
    Credentials,
    ErrorOut,
    PasswordChange,
    SessionOut,
    UserOut,
)
from investtrack.api.views import user_out
from investtrack.auth import (
    EmailTakenError,
    InvalidCredentialsError,
    InvalidEmailError,
    TooManyAttemptsError,
    WeakPasswordError,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def drop_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/api", httponly=True, samesite="strict")


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    responses={
        409: {"model": ErrorOut, "description": "Email already registered"},
        422: {"model": ErrorOut, "description": "Invalid email or weak password"},
    },
)
def register(payload: Credentials, session: SessionDep, request: Request) -> UserOut:
    """Create an account. The first account adopts data from before v0.5."""
    try:
        user = request.app.state.auth.register(session, payload.email, payload.password)
    except EmailTakenError as e:
        raise api_error(409, "EMAIL_TAKEN", e) from e
    except InvalidEmailError as e:
        raise api_error(422, "INVALID_EMAIL", e) from e
    except WeakPasswordError as e:
        raise api_error(422, "WEAK_PASSWORD", e) from e
    return user_out(user)


@router.post(
    "/login",
    responses={
        401: {"model": ErrorOut, "description": "Wrong email or password"},
        429: {"model": ErrorOut, "description": "Too many failed attempts"},
    },
)
def login(
    payload: Credentials, session: SessionDep, request: Request, response: Response
) -> SessionOut:
    try:
        token, expires = request.app.state.auth.login(
            session, payload.email, payload.password, client_ip(request)
        )
    except InvalidCredentialsError as e:
        raise api_error(401, "INVALID_CREDENTIALS", e) from e
    except TooManyAttemptsError as e:
        raise api_error(429, "TOO_MANY_ATTEMPTS", e) from e
    response.set_cookie(
        SESSION_COOKIE,
        token,
        expires=expires,
        httponly=True,
        samesite="strict",
        # Only over HTTPS when the site is on HTTPS (always, deployed);
        # plain http://localhost in development would otherwise drop it.
        secure=request.url.scheme == "https",
        path="/api",  # only the API needs it, not every asset request
    )
    return SessionOut(expires_at=expires)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(session: SessionDep, user: UserDep, request: Request, response: Response) -> None:
    request.app.state.auth.logout(session, session_token(request))
    drop_session_cookie(response)


@router.get("/me")
def me(user: UserDep) -> UserOut:
    return user_out(user)


@router.post(
    "/delete-account",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        # 403, not 401: a 401 means "no session", and the app would log out.
        403: {"model": ErrorOut, "description": "Wrong password"},
        429: {"model": ErrorOut, "description": "Too many failed attempts"},
    },
)
def delete_account(
    payload: AccountDeletion,
    session: SessionDep,
    user: UserDep,
    request: Request,
    response: Response,
) -> None:
    """Delete the account and all of its data. There is no undo."""
    try:
        request.app.state.auth.delete_account(session, user, payload.password, client_ip(request))
    except InvalidCredentialsError as e:
        raise api_error(403, "WRONG_PASSWORD", e) from e
    except TooManyAttemptsError as e:
        raise api_error(429, "TOO_MANY_ATTEMPTS", e) from e
    drop_session_cookie(response)


@router.post(
    "/password",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        # 403, not 401: a 401 means "no session", and the app would log out.
        403: {"model": ErrorOut, "description": "Wrong current password"},
        422: {"model": ErrorOut, "description": "Weak new password"},
        429: {"model": ErrorOut, "description": "Too many failed attempts"},
    },
)
def change_password(
    payload: PasswordChange, session: SessionDep, user: UserDep, request: Request
) -> None:
    """Change the password. Every other session of this account is ended."""
    try:
        request.app.state.auth.change_password(
            session,
            user,
            session_token(request),
            payload.current_password,
            payload.new_password,
            client_ip(request),
        )
    except InvalidCredentialsError as e:
        raise api_error(403, "WRONG_PASSWORD", e) from e
    except WeakPasswordError as e:
        raise api_error(422, "WEAK_PASSWORD", e) from e
    except TooManyAttemptsError as e:
        raise api_error(429, "TOO_MANY_ATTEMPTS", e) from e
