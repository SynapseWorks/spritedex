FROM node:24-alpine AS frontend-build
WORKDIR /build/frontend
COPY frontend/package.json ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SPRITEDEX_FRONTEND_DIST=/app/frontend/dist

RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt ./backend/requirements.txt
RUN python -m pip install -r backend/requirements.txt

COPY backend/ ./backend/
COPY database/ ./database/
COPY scripts/ ./scripts/
COPY --from=frontend-build /build/frontend/dist ./frontend/dist

EXPOSE 8000

CMD ["bash", "scripts/start_production.sh"]
