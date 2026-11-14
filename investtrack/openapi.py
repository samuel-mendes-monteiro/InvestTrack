"""Print the API's OpenAPI schema, the contract the web frontend is typed from.

    python -m investtrack.openapi > web/openapi.json

The schema is built from the route and Pydantic definitions alone, so this
needs no database, network or .env (the app's lifespan never runs).
"""

import json

from investtrack.api import create_app


def schema_json() -> str:
    # sort_keys + a trailing newline make the output stable, so CI can diff it.
    return json.dumps(create_app().openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    print(schema_json(), end="")
