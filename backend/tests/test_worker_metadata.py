import pytest
from sqlalchemy import select

from app import worker
from app.discovery.extraction import extract_recipe
from app.models import Household, Job, JobStatus, Recipe, RecipePublisherTag, RecipeVersion


def _pending_recipe(session_factory, title="Backfill soup"):
    with session_factory() as db:
        household = db.scalar(select(Household))
        recipe = Recipe(
            household_id=household.id,
            title=title,
            source_type="url",
            source_url=f"https://www.bbcgoodfood.com/recipes/{title.casefold().replace(' ', '-')}",
            publisher_metadata_status="pending",
        )
        db.add(recipe)
        db.flush()
        db.add(RecipeVersion(recipe_id=recipe.id, version_number=1, title=title))
        db.commit()
        return recipe.id


def test_metadata_backfill_persists_tags_without_changing_recipe_content(
    client, owner, session_factory, monkeypatch
):
    del client, owner
    recipe_id = _pending_recipe(session_factory)

    async def fake_extract(url):
        return extract_recipe(
            '''<script type="application/ld+json">{
              "@type":"Recipe", "name":"Publisher title", "recipeYield":"4",
              "recipeIngredient":["1 tomato"], "recipeCategory":["Soup", "Healthy"]
            }</script>''',
            url,
        )

    monkeypatch.setattr(worker, "SessionLocal", session_factory)
    monkeypatch.setattr(worker, "_fetch_and_extract", fake_extract)

    result = worker.backfill_recipe_publisher_metadata.run(batch_size=10)

    assert result == {"selected": 1, "refreshed": 1, "failed": 0, "skipped": 0}
    with session_factory() as db:
        recipe = db.get(Recipe, recipe_id)
        tags = db.scalars(
            select(RecipePublisherTag).where(RecipePublisherTag.recipe_id == recipe_id)
        ).all()
        assert recipe.title == "Backfill soup"
        assert recipe.publisher_metadata_status == "ready"
        assert recipe.publisher_metadata_attempts == 0
        assert recipe.publisher_metadata_refreshed_at is not None
        assert {tag.normalised_value for tag in tags} == {"soup", "healthy"}


def test_metadata_backfill_retries_three_times_then_stops(
    client, owner, session_factory, monkeypatch
):
    del client, owner
    recipe_id = _pending_recipe(session_factory, "Retry soup")

    async def broken_extract(url):
        del url
        raise RuntimeError("publisher unavailable")

    monkeypatch.setattr(worker, "SessionLocal", session_factory)
    monkeypatch.setattr(worker, "_fetch_and_extract", broken_extract)

    for _ in range(3):
        worker.backfill_recipe_publisher_metadata.run(batch_size=10)

    final = worker.backfill_recipe_publisher_metadata.run(batch_size=10)
    with session_factory() as db:
        recipe = db.get(Recipe, recipe_id)
        assert recipe.publisher_metadata_status == "failed"
        assert recipe.publisher_metadata_attempts == 3
        assert recipe.publisher_metadata_error == "publisher unavailable"
    assert final["selected"] == 0


def test_import_parser_failure_rolls_back_partial_recipe(
    client, owner, session_factory, monkeypatch
):
    del client
    with session_factory() as db:
        household = db.scalar(select(Household))
        job = Job(
            household_id=household.id,
            user_id=owner["user"]["id"],
            kind="recipe_import",
            status=JobStatus.QUEUED.value,
            payload={"url": "https://example.com/atomic-import"},
        )
        db.add(job)
        db.commit()
        job_id = job.id

    async def fake_extract(url):
        return extract_recipe(
            '''<script type="application/ld+json">{
              "@type":"Recipe", "name":"Atomic soup", "recipeYield":"4",
              "recipeIngredient":["1 tomato", "2 onions"]
            }</script>''',
            url,
        )

    original_parse = worker.parse_ingredient
    calls = 0

    def fail_second(line):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected parser failure")
        return original_parse(line)

    monkeypatch.setattr(worker, "SessionLocal", session_factory)
    monkeypatch.setattr(worker, "_fetch_and_extract", fake_extract)
    monkeypatch.setattr(worker, "parse_ingredient", fail_second)

    with pytest.raises(RuntimeError, match="injected parser failure"):
        worker.process_recipe_import.run(job_id)

    with session_factory() as db:
        assert db.scalar(select(Recipe).where(Recipe.title == "Atomic soup")) is None
        failed = db.get(Job, job_id)
        assert failed.status == JobStatus.FAILED.value
        assert failed.error_code == "IMPORT_FAILED"
        assert "injected" not in failed.error_detail
