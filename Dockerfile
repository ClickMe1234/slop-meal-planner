# syntax=docker/dockerfile:1.7

ARG NODE_IMAGE=node:22.18.0-bookworm-slim
ARG PYTHON_IMAGE=python:3.12.11-slim-bookworm
ARG POSTGRES_IMAGE=postgres:17.5-bookworm

FROM ${POSTGRES_IMAGE} AS postgres-tools

FROM ${NODE_IMAGE} AS frontend-build
WORKDIR /build/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci

COPY frontend/ ./
ARG VITE_API_URL=""
ARG VITE_DEMO_MODE="false"
ENV VITE_API_URL=${VITE_API_URL} \
    VITE_DEMO_MODE=${VITE_DEMO_MODE}
RUN npm run build

FROM ${PYTHON_IMAGE} AS python-build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/venv
RUN python -m venv "$VIRTUAL_ENV"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

WORKDIR /build/backend
COPY backend/ ./
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip setuptools wheel && \
    pip install ".[workers]" && \
    python -m nltk.downloader -d "$VIRTUAL_ENV/nltk_data" averaged_perceptron_tagger_eng

FROM ${PYTHON_IMAGE} AS runtime
ARG APP_VERSION=dev
ARG APP_REVISION=unknown

LABEL org.opencontainers.image.title="Meal Planner" \
      org.opencontainers.image.description="Private household meal planning application" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${APP_REVISION}"

ENV APP_VERSION=${APP_VERSION} \
    APP_REVISION=${APP_REVISION} \
    PATH="/opt/venv/bin:$PATH" \
    NLTK_DATA="/opt/venv/nltk_data" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FRONTEND_DIST_DIR=/app/frontend/dist \
    HOME=/tmp

RUN apt-get update && \
    apt-get install -y --no-install-recommends gosu postgresql-client && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd --gid 10001 mealplanner && \
    useradd --uid 10001 --gid mealplanner --no-create-home --shell /usr/sbin/nologin mealplanner && \
    mkdir -p /app/backend /app/frontend/dist /data && \
    chown -R mealplanner:mealplanner /app /data

# Debian Bookworm's default client is PostgreSQL 15.  Use the PostgreSQL 17
# utility that matches the database image so in-app backups cannot fail with a
# server/client version mismatch.
COPY --from=postgres-tools /usr/lib/postgresql/17/bin/pg_dump /usr/local/bin/pg_dump
COPY --from=postgres-tools /usr/lib/postgresql/17/bin/pg_restore /usr/local/bin/pg_restore

COPY --from=python-build /opt/venv /opt/venv
COPY --chown=mealplanner:mealplanner backend/ /app/backend/
COPY --from=frontend-build --chown=mealplanner:mealplanner /build/frontend/dist/ /app/frontend/dist/
COPY --chown=mealplanner:mealplanner deploy/docker/entrypoint.sh /usr/local/bin/meal-planner-entrypoint
COPY --chown=mealplanner:mealplanner deploy/scripts/backup.sh /opt/meal-planner/backup.sh
RUN chmod 0555 /usr/local/bin/meal-planner-entrypoint /opt/meal-planner/backup.sh

WORKDIR /app/backend
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/ready', timeout=3)"]

ENTRYPOINT ["meal-planner-entrypoint"]
CMD ["web"]
