"""HTTP layer (FastAPI).

Endpoints are thin: they convert JSON to domain objects, call the
repository, and translate domain errors into HTTP status codes.

Run with:  uvicorn investtrack.api:app --reload
"""

from investtrack.api.app import app, create_app

__all__ = ["app", "create_app"]
