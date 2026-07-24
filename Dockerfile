# syntax=docker/dockerfile:1.7

ARG NODE_IMAGE=node:22-bookworm-slim@sha256:6c74791e557ce11fc957704f6d4fe134a7bc8d6f5ca4403205b2966bd488f6b3
ARG PYTHON_IMAGE=python:3.12.13-slim-bookworm@sha256:d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b
ARG POSTGRES_TOOLS_IMAGE=postgres:18.4-bookworm@sha256:1961f96e6029a02c3812d7cb329a3b03a3ac2bb067058dec17b0f5596aca9296

FROM ${POSTGRES_TOOLS_IMAGE} AS postgres-tools

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
    pip install pip==26.1.2 setuptools==83.0.0 wheel==0.47.0 && \
    pip install --require-hashes --no-build-isolation -r requirements.lock && \
    mkdir -p "$VIRTUAL_ENV/nltk_data/taggers" && \
    python -c "import urllib.request; urllib.request.urlretrieve('https://raw.githubusercontent.com/nltk/nltk_data/550b6625bcef1f2abff2ff770a5a0d272c9c6b2a/packages/taggers/averaged_perceptron_tagger_eng.zip', '/tmp/tagger.zip')" && \
    echo "6025f530624335c67d6547d44757b357b4e79bae030a0383e9887a92c1718f0b  /tmp/tagger.zip" | sha256sum --check --strict && \
    python -m zipfile -e /tmp/tagger.zip "$VIRTUAL_ENV/nltk_data/taggers" && \
    rm /tmp/tagger.zip && \
    NLTK_DATA="$VIRTUAL_ENV/nltk_data" python -c \
      "import nltk; nltk.data.find('taggers/averaged_perceptron_tagger_eng')"

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
    apt-get install -y --no-install-recommends gosu=1.14-1+b10 postgresql-client=15+248+deb12u1 && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd --gid 10001 mealplanner && \
    useradd --uid 10001 --gid mealplanner --no-create-home --shell /usr/sbin/nologin mealplanner && \
    mkdir -p /app/backend /app/frontend/dist /data && \
    chown mealplanner:mealplanner /data

# Bundle PostgreSQL 18.4 client utilities.  pg_dump/pg_restore can work with
# supported PostgreSQL 15-18 servers, while the database containers retain
# their own lifecycle and major-version data directories.
COPY --from=postgres-tools /usr/lib/postgresql/18/bin/pg_dump /usr/local/bin/pg_dump
COPY --from=postgres-tools /usr/lib/postgresql/18/bin/pg_restore /usr/local/bin/pg_restore
COPY --from=postgres-tools /usr/lib/postgresql/18/bin/psql /usr/local/bin/psql
COPY --from=postgres-tools /usr/lib/postgresql/18/bin/dropdb /usr/local/bin/dropdb
COPY --from=postgres-tools /usr/lib/postgresql/18/bin/createdb /usr/local/bin/createdb
COPY --from=postgres-tools /usr/lib/x86_64-linux-gnu/libpq.so.5.18 /usr/local/lib/libpq.so.5.18
RUN ln -s libpq.so.5.18 /usr/local/lib/libpq.so.5 && ldconfig

COPY --from=python-build /opt/venv /opt/venv
COPY backend/ /app/backend/
COPY --from=frontend-build /build/frontend/dist/ /app/frontend/dist/
COPY deploy/docker/entrypoint.sh /usr/local/bin/meal-planner-entrypoint
COPY deploy/docker/launcher.py /opt/meal-planner/launcher.py
COPY deploy/scripts/backup.sh /opt/meal-planner/backup.sh
COPY deploy/scripts/restore.sh /opt/meal-planner/restore.sh
RUN chmod 0555 /usr/local/bin/meal-planner-entrypoint /opt/meal-planner/launcher.py \
    /opt/meal-planner/backup.sh /opt/meal-planner/restore.sh && \
    chmod -R a-w /app /opt/meal-planner

WORKDIR /app/backend
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/ready', timeout=3)"]

ENTRYPOINT ["meal-planner-entrypoint"]
CMD ["all"]
