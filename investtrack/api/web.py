"""Serving the built React app (web/dist) from the same origin as the API."""

from pathlib import Path

from fastapi import FastAPI, status
from fastapi.responses import FileResponse, JSONResponse


def serve_web(app: FastAPI, web_dir: Path) -> None:
    """Serve the built web app, with index.html for every other path.

    The app routes in the browser (/proventos, /patrimonio...), so reloading
    one of those pages asks the server for a path that is not a file: it
    must get index.html, and the React router takes it from there.
    """
    root = web_dir.resolve()
    index = root / "index.html"
    forever = {"Cache-Control": "public, max-age=31536000, immutable"}

    @app.get("/{path:path}", include_in_schema=False)
    def web(path: str):
        if path == "api" or path.startswith("api/"):  # an API typo is a 404, not the app
            return JSONResponse({"detail": "Not Found"}, status.HTTP_404_NOT_FOUND)
        file = (root / path).resolve()
        if path and file.is_file() and file.is_relative_to(root):  # no ../ escapes
            # Vite puts a hash of the content in every name under assets/, so
            # they can be cached forever: a new build has new names.
            if path.startswith("assets/"):
                return FileResponse(file, headers=forever)
            return FileResponse(file)
        # index.html names the current assets, so it must always be fresh.
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
