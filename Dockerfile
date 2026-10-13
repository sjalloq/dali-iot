# Two stages: Node builds the SPA into the package, Python ships it.
# The server needs no Node; the image needs no gateway at build time.
FROM node:22-alpine AS web
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY --from=web /build/src/dali_iot/web/static ./src/dali_iot/web/static
RUN uv sync --frozen --no-dev --extra web

# Mount the site file at /data/site.yaml and set DALI_IOT_URL (see docker-compose.yml).
EXPOSE 8000
CMD ["uv", "run", "--frozen", "--no-dev", "dali-iot", "serve", "--host", "0.0.0.0", "--port", "8000", "--site", "/data/site.yaml"]
