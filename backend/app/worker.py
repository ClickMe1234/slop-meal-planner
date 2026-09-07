"""Celery entry point and idempotent background jobs."""
from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import os
from urllib.parse import urlparse

import httpx
from celery import Celery
from sqlalchemy import delete, select, text

from .db import SessionLocal
from .discovery import canonicalize_url, default_registry, extract_recipe
from .discovery.errors import UnsupportedSourceError
from .discovery.http import PoliteHttpFetcher
from .models import (
    Job,
    JobStatus,
    Recipe,
    RecipeEligibility,
    RecipeIngredient,
    RecipeMethodSnapshot,
    RecipePublisherTag,
    RecipeVersion,
    PublisherMetadataStatus,
    UserSession,
)
from .services.ingredient_names import ingredient_name_keys, preferred_ingredient_name
from .services.ingredients import PARSER_VERSION, parse_ingredient
from .services.nutrition import publisher_values
from .services.recipe_methods import snapshot_values, source_blocks_from_extracted

celery_app = Celery(
    "meal_planner",
    broker=os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0"),
    backend=os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/1"),
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone=os.getenv("MEAL_PLANNER_TIMEZONE", "Europe/London"),
    task_track_started=True,
    beat_schedule={
        "cleanup-expired-state-nightly": {
            "task": "app.worker.cleanup_expired_state",
            "schedule": 24 * 60 * 60,
        },
        "backfill-recipe-publisher-metadata": {
            "task": "app.worker.backfill_recipe_publisher_metadata",
            "schedule": 10 * 60,
        },
        "recover-stale-recipe-imports": {
            "task": "app.worker.recover_stale_recipe_imports",
            "schedule": 5 * 60,
        },
    },
)


async def _fetch_and_extract(url: str):
    canonical = canonicalize_url(url)
    host = urlparse(canonical).hostname or ""
    try:
        adapter = default_registry.for_url(canonical)
        allowed_hosts = set(adapter.hosts)
    except UnsupportedSourceError:
        # Generic custom-site import remains available, but redirects may not
        # escape the submitted publisher host.
        allowed_hosts = {host, host.removeprefix("www."), f"www.{host.removeprefix('www.')}"}
    fetcher = PoliteHttpFetcher()
    try:
        html = await fetcher.fetch_text(canonical, allowed_hosts=allowed_hosts)
    finally:
        await fetcher.aclose()
    return extract_recipe(html, canonical)


def _json_safe(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _replace_publisher_tags(db, recipe: Recipe, extracted) -> None:
    db.execute(delete(RecipePublisherTag).where(RecipePublisherTag.recipe_id == recipe.id))
    for tag in extracted.publisher_tags:
        db.add(
            RecipePublisherTag(
                recipe_id=recipe.id,
                kind=tag.kind,
                label=tag.label,
                normalised_value=tag.normalised_value,
            )
        )
    recipe.publisher_metadata_status = PublisherMetadataStatus.READY.value
    recipe.publisher_metadata_attempts = 0
    recipe.publisher_metadata_refreshed_at = datetime.now(timezone.utc)
    recipe.publisher_metadata_error = None


@celery_app.task
def cleanup_expired_state() -> dict[str, int]:
    now = datetime.now(timezone.utc)
    job_cutoff = now - timedelta(days=30)
    with SessionLocal() as db:
        sessions = db.execute(delete(UserSession).where(UserSession.expires_at < now)).rowcount or 0
        jobs = db.execute(
            delete(Job).where(
                Job.status.in_(
                    [
                        JobStatus.SUCCEEDED.value,
                        JobStatus.FAILED.value,
                        JobStatus.CANCELLED.value,
                    ]
                ),
                Job.updated_at < job_cutoff,
            )
        ).rowcount or 0
        db.commit()
    return {"sessions_deleted": sessions, "jobs_deleted": jobs}


@celery_app.task
def backfill_recipe_publisher_metadata(batch_size: int = 10) -> dict[str, int]:
    """Refresh supported publisher tags without changing saved recipe content."""

    stale_before = datetime.now(timezone.utc) - timedelta(minutes=30)
    with SessionLocal() as db:
        recipes = db.scalars(
            select(Recipe)
            .where(
                Recipe.source_type == "url",
                Recipe.source_url.is_not(None),
                Recipe.publisher_metadata_attempts < 3,
                (
                    (Recipe.publisher_metadata_status == PublisherMetadataStatus.PENDING.value)
                    | (
                        (Recipe.publisher_metadata_status == PublisherMetadataStatus.REFRESHING.value)
                        & (Recipe.updated_at < stale_before)
                    )
                ),
            )
            .order_by(Recipe.updated_at, Recipe.id)
            .limit(max(1, min(batch_size, 50)))
            .with_for_update(skip_locked=True)
        ).all()
        recipe_ids = [recipe.id for recipe in recipes]
        for recipe in recipes:
            recipe.publisher_metadata_status = PublisherMetadataStatus.REFRESHING.value
            recipe.publisher_metadata_attempts += 1
            recipe.publisher_metadata_error = None
        db.commit()

        refreshed = failed = skipped = 0
        for recipe_id in recipe_ids:
            recipe = db.get(Recipe, recipe_id)
            if recipe is None or not recipe.source_url:
                skipped += 1
                continue
            try:
                default_registry.for_url(recipe.source_url)
            except UnsupportedSourceError:
                recipe.publisher_metadata_status = PublisherMetadataStatus.NOT_APPLICABLE.value
                recipe.publisher_metadata_error = "Publisher tags are not supported for this website"
                skipped += 1
                db.commit()
                continue
            try:
                extracted = asyncio.run(_fetch_and_extract(recipe.source_url))
                _replace_publisher_tags(db, recipe, extracted)
                refreshed += 1
            except Exception as exc:
                recipe.publisher_metadata_status = (
                    PublisherMetadataStatus.FAILED.value
                    if recipe.publisher_metadata_attempts >= 3
                    else PublisherMetadataStatus.PENDING.value
                )
                recipe.publisher_metadata_error = str(exc)[:500]
                failed += 1
            db.commit()
    return {
        "selected": len(recipe_ids),
        "refreshed": refreshed,
        "failed": failed,
        "skipped": skipped,
    }


def _import_transient(exc: BaseException) -> bool:
    """Return whether an import failure is safe to replay.

    Discovery fetches are the only external side effect in an import.  Parser
    and database errors must not be replayed automatically: doing so can hide
    malformed publisher data and, more importantly, makes it much harder to
    reason about an import which has already committed part of its work.
    """

    return isinstance(exc, (httpx.TransportError, TimeoutError, ConnectionError))


def _import_lock_key(household_id: str, canonical_url: str) -> int:
    """Produce a stable signed PostgreSQL advisory-lock key for one URL."""

    digest = hashlib.blake2b(
        f"recipe-import:{household_id}:{canonical_url}".encode("utf-8"),
        digest_size=8,
    ).digest()
    return int.from_bytes(digest, byteorder="big", signed=True)


def _lock_import_if_supported(db, household_id: str, canonical_url: str) -> None:
    """Serialise duplicate imports on PostgreSQL without changing the schema.

    SQLite is deliberately left alone because its test fixtures and local demo
    mode do not expose PostgreSQL advisory locks.  The duplicate query remains
    correct there for sequential/retried deliveries.
    """

    bind = db.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": _import_lock_key(household_id, canonical_url)},
        )


def _mark_import_failure(job_id: str, exc: BaseException, *, retrying: bool) -> None:
    """Record failure in a clean transaction after rolling back recipe work."""

    with SessionLocal() as failure_db:
        failed_job = failure_db.get(Job, job_id)
        if failed_job is None:
            return
        # A duplicate delivery may fail after another worker has already
        # completed the same import.  Preserve the freshly committed terminal
        # result instead of replacing it with this stale worker's outcome.
        if failed_job.status in (
            JobStatus.AWAITING_REVIEW.value,
            JobStatus.SUCCEEDED.value,
        ):
            return
        if retrying:
            failed_job.status = JobStatus.QUEUED.value
            failed_job.stage = "retrying"
            failed_job.error_code = "IMPORT_RETRYING"
            failed_job.error_detail = "The publisher could not be reached; retrying automatically."
            failed_job.progress = 10
        else:
            failed_job.status = JobStatus.FAILED.value
            failed_job.stage = "failed"
            failed_job.error_code = "IMPORT_FAILED"
            failed_job.error_detail = (
                "The recipe could not be imported. Check the source and retry; "
                "operators can inspect worker logs for the underlying error."
            )
        failure_db.commit()


@celery_app.task(bind=True, autoretry_for=(httpx.TransportError, TimeoutError, ConnectionError), retry_backoff=True, retry_jitter=True, max_retries=4)
def process_recipe_import(self, job_id: str) -> dict:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None:
            return {"ignored": "job no longer exists"}
        if job.status in (JobStatus.AWAITING_REVIEW.value, JobStatus.SUCCEEDED.value):
            return job.result or {}
        job.status = JobStatus.RUNNING.value
        job.stage = "fetching"
        job.progress = 10
        db.commit()
        try:
            extracted = asyncio.run(_fetch_and_extract(job.payload["url"]))
            job.stage = "extracting"
            job.progress = 45
            db.commit()

            # Hold a transaction-scoped lock across the duplicate check and
            # recipe creation.  Without this, two deliveries for the same URL
            # can both observe an empty library and create two versions.
            _lock_import_if_supported(db, job.household_id, extracted.canonical_url)
            existing = db.scalar(
                select(Recipe).where(
                    Recipe.household_id == job.household_id,
                    Recipe.source_url == extracted.canonical_url,
                )
            )
            if existing is not None:
                _replace_publisher_tags(db, existing, extracted)
                job.status = JobStatus.AWAITING_REVIEW.value
                job.stage = "recipe_review"
                job.progress = 100
                job.result = {"recipe_id": existing.id, "already_saved": True}
                db.commit()
                return job.result

            recipe = Recipe(
                household_id=job.household_id,
                title=extracted.title,
                eligibility=RecipeEligibility.NEEDS_REVIEW.value,
                source_type="url",
                source_url=extracted.canonical_url,
                publisher=extracted.publisher or urlparse(extracted.canonical_url).hostname,
                image_url=extracted.image_url,
                publisher_metadata_status=PublisherMetadataStatus.READY.value,
                publisher_metadata_refreshed_at=datetime.now(timezone.utc),
            )
            db.add(recipe)
            db.flush()
            _replace_publisher_tags(db, recipe, extracted)
            version = RecipeVersion(
                recipe_id=recipe.id,
                version_number=1,
                title=extracted.title,
                yield_servings=extracted.yield_servings,
                publisher_nutrition=(
                    _json_safe(asdict(extracted.publisher_nutrition))
                    if extracted.publisher_nutrition
                    else None
                ),
            )
            db.add(version)
            db.flush()
            created_ingredients = []
            for position, line in enumerate(extracted.ingredient_lines):
                parsed = parse_ingredient(line)
                name_keys = ingredient_name_keys(db, parsed.food_phrase)
                display_name, remembered = preferred_ingredient_name(
                    db,
                    job.household_id,
                    name_keys,
                    parsed.food_phrase,
                )
                ingredient = RecipeIngredient(
                        recipe_version_id=version.id,
                        position=position,
                        original_text=line,
                        quantity=parsed.quantity,
                        unit=parsed.unit,
                        quantity_grams=parsed.quantity_grams,
                        food_phrase=display_name,
                        parsed_food_phrase=parsed.food_phrase,
                        preparation=parsed.preparation,
                        parser_version=PARSER_VERSION,
                        name_confidence=(
                            Decimal(str(round(parsed.name_confidence, 4)))
                            if parsed.name_confidence is not None
                            else None
                        ),
                        name_overridden=remembered,
                        parser_name_keys=name_keys,
                        included=not parsed.optional,
                        optional=parsed.optional,
                        needs_review=parsed.needs_review and not remembered,
                    )
                db.add(ingredient)
                created_ingredients.append(ingredient)
            db.flush()
            blocks = source_blocks_from_extracted(extracted.instruction_blocks)
            if blocks:
                db.add(
                    RecipeMethodSnapshot(
                        recipe_version_id=version.id,
                        **snapshot_values(
                            blocks=blocks,
                            ingredients=created_ingredients,
                            source_kind="publisher",
                            extractor_version=extracted.extraction_method,
                            created_by_user_id=job.user_id,
                        ),
                    )
                )
            if publisher_values(version) is not None and version.yield_servings:
                recipe.eligibility = RecipeEligibility.PLANNER_READY.value
            else:
                recipe.eligibility = RecipeEligibility.DRAFT.value
            job.status = JobStatus.AWAITING_REVIEW.value
            job.stage = "recipe_review"
            job.progress = 80
            job.result = {
                "recipe_id": recipe.id,
                "recipe_version_id": version.id,
                "extraction_method": extracted.extraction_method,
                "review_reasons": list(extracted.review_reasons),
            }
            db.commit()
            return job.result
        except Exception as exc:
            # Recipe/version/ingredient work is intentionally uncommitted at
            # this point.  Roll it back before recording the job outcome in a
            # fresh session; otherwise a parser failure leaves a partial
            # recipe beside a failed job.
            db.rollback()
            retrying = _import_transient(exc) and getattr(self.request, "retries", 0) < self.max_retries
            _mark_import_failure(job_id, exc, retrying=retrying)
            raise


@celery_app.task
def recover_stale_recipe_imports(
    stale_minutes: int = 30,
    max_recoveries: int = 3,
) -> dict[str, int]:
    """Requeue imports abandoned by a worker or broker outage.

    The job payload is the only persisted metadata available without a schema
    migration, so recovery count is kept under a private key.  A job is only
    submitted after its status has been committed as queued.  If the broker is
    still unavailable it remains visible and will be picked up by the next
    scheduler pass rather than being lost.
    """

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max(1, stale_minutes))
    recovered = failed = submitted = 0
    job_ids: list[str] = []
    with SessionLocal() as db:
        jobs = db.scalars(
            select(Job)
            .where(
                Job.kind == "recipe_import",
                Job.status.in_((JobStatus.QUEUED.value, JobStatus.RUNNING.value)),
                Job.updated_at < cutoff,
            )
            .order_by(Job.updated_at, Job.id)
            .limit(100)
            .with_for_update(skip_locked=True)
        ).all()
        for job in jobs:
            payload = dict(job.payload or {})
            attempts = int(payload.get("_stale_recovery_count", 0))
            if attempts >= max_recoveries:
                job.status = JobStatus.FAILED.value
                job.stage = "failed"
                job.error_code = "IMPORT_STALE"
                job.error_detail = "The import worker did not complete this job. Start a new import."
                failed += 1
                continue
            payload["_stale_recovery_count"] = attempts + 1
            job.payload = payload
            job.status = JobStatus.QUEUED.value
            job.stage = "requeued"
            job.error_code = "IMPORT_REQUEUED"
            job.error_detail = "The import worker was unavailable; the job is being retried."
            job.progress = 0
            job_ids.append(job.id)
            recovered += 1
        db.commit()

    for job_id in job_ids:
        try:
            process_recipe_import.delay(job_id)
            submitted += 1
        except Exception:
            # The persisted queued job is the recovery record.  Do not raise
            # here: one broker outage must not prevent other stale jobs from
            # being inspected on the next scheduler pass.
            continue
    return {"recovered": recovered, "submitted": submitted, "failed": failed}
