"""Domain errors as HTTP errors with stable, machine-readable codes."""

from fastapi import HTTPException

from investtrack.auth import TooManyAttemptsError
from investtrack.core.fixed_income import RedemptionTooLargeError
from investtrack.core.income import IncomeWithoutPositionError
from investtrack.core.portfolio import InsufficientPositionError


def api_error(status_code: int, code: str, error: Exception) -> HTTPException:
    """An HTTP error with a stable machine-readable code.

    Clients translate the code into their own language and can use the
    extra fields (ticker, available, requested) to build the message.
    The English `message` is a fallback for codes a client doesn't know.
    """
    detail = {"code": code, "message": str(error)}
    if isinstance(error, InsufficientPositionError):
        detail |= {
            "ticker": error.ticker,
            "available": str(error.available),
            "requested": str(error.requested),
        }
    elif isinstance(error, IncomeWithoutPositionError):
        detail |= {
            "ticker": error.ticker,
            "income_date": error.date.isoformat(),
            "first_buy": error.first_buy.isoformat() if error.first_buy else None,
        }
    elif isinstance(error, TooManyAttemptsError):
        detail["retry_after"] = error.retry_after
        # Also the standard header, for clients that only look there.
        return HTTPException(status_code, detail, headers={"Retry-After": str(error.retry_after)})
    elif isinstance(error, RedemptionTooLargeError):
        detail |= {"date": error.day.isoformat(), "available": str(error.available)}
    return HTTPException(status_code, detail)
