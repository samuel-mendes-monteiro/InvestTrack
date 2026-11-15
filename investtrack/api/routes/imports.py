"""Importing B3's trade statement (Negociação, in Excel): preview, then import."""

from fastapi import APIRouter
from sqlalchemy.orm import Session

from investtrack.api.deps import XLSX, EventsDep, SessionDep, StatementDep, UserDep
from investtrack.api.errors import api_error
from investtrack.api.schemas import ErrorOut, ImportOut, ImportRowOut, SkippedRowOut
from investtrack.sources.b3_statement import StatementError, read_statement
from investtrack.storage import repository
from investtrack.storage.events import EventSource
from investtrack.storage.models import User

router = APIRouter(prefix="/imports", tags=["import"])

STATEMENT_BODY = {
    "requestBody": {
        "content": {XLSX: {"schema": {"type": "string", "format": "binary"}}},
        "description": "The trade statement (Negociação) from B3's Área do Investidor",
    }
}
IMPORT_ERRORS = {
    413: {"model": ErrorOut, "description": "File larger than 5 MB"},
    422: {"model": ErrorOut, "description": "Not a B3 trade statement"},
}


def statement_result(
    session: Session, user: User, events: EventSource, data: bytes, save: bool
) -> ImportOut:
    # (user comes first in the endpoints: FastAPI resolves dependencies in
    # parameter order, so an anonymous upload is refused before being read)
    try:
        rows, skipped = read_statement(data)
    except StatementError as e:
        raise api_error(422, "INVALID_STATEMENT", e) from e
    action = repository.import_statement if save else repository.plan_statement_import
    plan = action(session, user.id, rows, events)

    def out(p) -> ImportRowOut:
        status = "IMPORTED" if save and p.status == "NEW" else str(p.status)
        error = api_error(422, "INSUFFICIENT_POSITION", p.error).detail if p.error else None
        return ImportRowOut(
            line=p.row.line,
            status=status,
            date=p.row.date,
            op_type=p.row.op_type,
            ticker=p.row.ticker,
            quantity=p.row.quantity,
            price=p.row.price,
            error=error,
        )

    def count(status: str) -> int:
        return sum(1 for p in plan if p.status == status)

    return ImportOut(
        imported=save,
        new=count("NEW"),
        duplicates=count("DUPLICATE"),
        rejected=count("REJECTED"),
        skipped=len(skipped),
        rows=[out(p) for p in plan],
        skipped_rows=[
            SkippedRowOut(line=s.line, reason=s.reason, detail=s.detail) for s in skipped
        ],
    )


@router.post("/b3/preview", openapi_extra=STATEMENT_BODY, responses=IMPORT_ERRORS)
def preview_b3_import(
    user: UserDep, data: StatementDep, session: SessionDep, events: EventsDep
) -> ImportOut:
    """What importing the statement would add. Nothing is saved."""
    return statement_result(session, user, events, data, save=False)


@router.post("/b3", openapi_extra=STATEMENT_BODY, responses=IMPORT_ERRORS)
def import_b3(
    user: UserDep, data: StatementDep, session: SessionDep, events: EventsDep
) -> ImportOut:
    """Add the statement's new trades, all in one transaction.

    Duplicates are left out and rejected tickers are not imported. The
    file is sent again instead of reusing the preview: the server keeps
    no state between the two calls.
    """
    return statement_result(session, user, events, data, save=True)
