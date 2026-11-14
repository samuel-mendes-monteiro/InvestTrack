# One image with everything: FastAPI serves the API under /api and the built
# React app on every other path, from the same origin.

# --- 1. Build the web app (Node is only needed here, not in the final image)
FROM node:24-slim AS web
WORKDIR /web
# Dependencies first: this layer is reused while package*.json don't change.
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
# Type checking and tests run in CI; the image only needs the bundle.
RUN npx vite build

# --- 2. The server
FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    WEB_DIST=/app/web/dist \
    DATABASE_URL=sqlite:////data/investtrack.db
WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY investtrack ./investtrack
RUN pip install --no-cache-dir .
COPY --from=web /web/dist ./web/dist
COPY deploy/entrypoint.sh /entrypoint.sh

# The server runs as an unprivileged user; the entrypoint (as root) only
# hands it the data volume, which the host mounts owned by root.
RUN useradd --system --no-create-home app && mkdir /data
VOLUME /data
EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
# --proxy-headers: behind Fly's proxy, trust X-Forwarded-For/-Proto, so the
# login limit sees each client's IP (not the proxy's) and the request is
# known to be HTTPS (the session cookie is then marked Secure). Only the
# proxy can reach the app, so trusting any forwarder is safe here.
# One worker: the login limit is kept in memory, per process.
CMD ["uvicorn", "investtrack.api:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
