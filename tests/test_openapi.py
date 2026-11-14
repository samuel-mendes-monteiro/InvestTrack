"""The committed web/openapi.json is the contract the frontend's types come from."""

from pathlib import Path

from investtrack.openapi import schema_json

COMMITTED = Path(__file__).parent.parent / "web" / "openapi.json"


def test_committed_schema_matches_the_api():
    # If this fails, the API changed: regenerate the schema and the frontend
    # types (cd web && npm run gen:api) and fix whatever no longer type-checks.
    assert COMMITTED.read_text(encoding="utf-8") == schema_json(), (
        "web/openapi.json is stale: run `cd web && npm run gen:api`"
    )
