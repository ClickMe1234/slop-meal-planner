"""Celery entry point and idempotent background jobs."""
from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
from urllib.parse import urlparse

import httpx
from celery import Celery
from sqlalchemy import delete, select

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
    RecipeVersion,
    UserSession,
)
from .services.ingredient_names import ingredient_name_keys, preferred_ingredient_name
from .services.ingredients import PARSER_VERSION, parse_ingredient
from .services.nutrition import publisher_values

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
        }
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


@celery_app.task(bind=True, autoretry_for=(httpx.TransportError,), retry_backoff=True, max_retries=3)
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

            existing = db.scalar(
                select(Recipe).where(
                    Recipe.household_id == job.household_id,
                    Recipe.source_url == extracted.canonical_url,
                )
            )
            if existing is not None:
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
            )
            db.add(recipe)
            db.flush()
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
            for position, line in enumerate(extracted.ingredient_lines):
                parsed = parse_ingredient(line)
                name_keys = ingredient_name_keys(db, parsed.food_phrase)
                display_name, remembered = preferred_ingredient_name(
                    db,
                    job.household_id,
                    name_keys,
                    parsed.food_phrase,
                )
                db.add(
                    RecipeIngredient(
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
            job.status = JobStatus.FAILED.value
            job.stage = "failed"
            job.error_code = "IMPORT_FAILED"
            job.error_detail = str(exc)[:1000]
            db.commit()
            raise
