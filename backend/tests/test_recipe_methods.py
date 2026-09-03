from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from app.schemas import MethodDocument
from app.services.recipe_methods import parse_method_document


def _headers(owner):
    return {"X-CSRF-Token": owner["csrf_token"]}


def _custom_recipe(client, owner, custom_instructions=None):
    response = client.post(
        "/api/v1/recipes",
        headers=_headers(owner),
        json={
            "title": "Two-stage courgettes",
            "source_type": "custom",
            "yield_servings": 4,
            "custom_instructions": custom_instructions or (
                "Fry half the zucchini in a pan for 5 minutes. "
                "Add the remaining zucchini and bake at 200C until tender."
            ),
            "meal_types": ["dinner"],
            "ingredients": [
                {
                    "original_text": "2 zucchini",
                    "quantity": 2,
                    "unit": "item",
                    "food_phrase": "zucchini",
                    "included": True,
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_rule_parser_builds_actions_semantics_portions_and_edges():
    ingredients = [
        {
            "lineage_id": "zucchini-lineage",
            "food_phrase": "zucchini",
            "original_text": "2 zucchini",
            "parser_name_keys": ["zucchini", "courgette"],
        },
        {
            "lineage_id": "oil-lineage",
            "food_phrase": "olive oil",
            "original_text": "1 tbsp olive oil",
            "parser_name_keys": ["olive oil"],
        },
    ]
    blocks = [
        {
            "id": "block-1",
            "position": 0,
            "heading": "Cook",
            "text": (
                "Fry half the zucchini with olive oil in a pan for 4-6 minutes. "
                "Add the remaining zucchini and bake at 200C until tender."
            ),
        }
    ]

    document, coverage, confidence = parse_method_document(blocks, ingredients)

    assert coverage == {
        "total_clauses": 2,
        "represented": 2,
        "omitted": 0,
        "unreviewed": 0,
    }
    assert confidence == Decimal("0.8800")
    assert [action.text for action in document.actions] == [
        "Fry half the zucchini with olive oil in a pan for 4-6 minutes",
        "Add the remaining zucchini and bake at 200C until tender",
    ]
    assert document.actions[0].duration_minutes == Decimal("5")
    assert document.actions[0].equipment == ["pan"]
    assert document.actions[1].temperature_value == Decimal("200")
    assert document.actions[1].cue == "tender"
    assert [binding.portion_mode for binding in document.ingredient_bindings] == [
        "fraction",
        "unspecified",
        "remainder",
    ]
    assert len(document.edges) == 1
    assert document.edges[0].kind == "sequence"


def test_custom_method_is_saved_scaled_localised_and_versioned(client, owner, session_factory):
    from app.models import IngredientNameEquivalent

    with session_factory() as db:
        db.add(IngredientNameEquivalent(us_name="zucchini", uk_name="courgette", priority=10))
        db.commit()
    recipe = _custom_recipe(client, owner)
    assert recipe["method_available"] is True
    assert recipe["method_status"] == "needs_review"

    response = client.get(f"/api/v1/recipes/{recipe['id']}/method?servings=8")
    assert response.status_code == 200, response.text
    method = response.json()
    assert method["requested_servings"] == "8"
    assert method["ingredients"][0]["quantity_text"] == "4"
    assert method["ingredients"][0]["name"] == "courgette"
    ingredient_segments = [
        segment
        for block in method["rendered_blocks"]
        for segment in block["segments"]
        if segment["kind"] == "ingredient"
    ]
    assert [segment["text"] for segment in ingredient_segments] == ["courgette", "courgette"]
    assert all(segment["quantity_label"].startswith("2 item") for segment in ingredient_segments)

    document = MethodDocument.model_validate(method["method"])
    updated = document.model_copy(deep=True)
    updated.actions[0].text = "Gently fry half the courgette"
    update_response = client.put(
        f"/api/v1/recipes/{recipe['id']}/method",
        headers=_headers(owner),
        json={
            "expected_version": method["recipe_version"],
            "method": updated.model_dump(mode="json"),
            "household_notes": "Use the heavy pan.",
            "mark_reviewed": False,
            "source_kind": "custom",
            "source_blocks": method["source_blocks"],
        },
    )
    assert update_response.status_code == 200, update_response.text
    saved = update_response.json()
    assert saved["recipe_version_number"] == method["recipe_version_number"] + 1
    assert saved["recipe_version"] == method["recipe_version"] + 1
    assert saved["method"]["actions"][0]["text"] == "Gently fry half the courgette"
    assert saved["household_notes"] == "Use the heavy pan."

    conflict = client.put(
        f"/api/v1/recipes/{recipe['id']}/method",
        headers=_headers(owner),
        json={
            "expected_version": method["recipe_version"],
            "method": updated.model_dump(mode="json"),
            "source_kind": "custom",
            "source_blocks": method["source_blocks"],
        },
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "VERSION_CONFLICT"

    with session_factory() as db:
        from app.models import RecipeVersion
        from sqlalchemy import func, select

        version_count = db.scalar(
            select(func.count(RecipeVersion.id)).where(RecipeVersion.recipe_id == recipe["id"])
        )
    assert version_count == 2


def test_custom_method_wording_is_persisted_on_the_recipe_version(client, owner):
    recipe = _custom_recipe(client, owner, "Fry the zucchini in a pan for 5 minutes.")
    initial = client.get(f"/api/v1/recipes/{recipe['id']}/method").json()
    document = MethodDocument.model_validate(initial["method"])
    updated_text = "Cook the zucchini in a pan for 5 minutes."

    response = client.put(
        f"/api/v1/recipes/{recipe['id']}/method",
        headers=_headers(owner),
        json={
            "expected_version": initial["recipe_version"],
            "method": document.model_dump(mode="json"),
            "mark_reviewed": False,
            "source_kind": "custom",
            "source_blocks": [{**initial["source_blocks"][0], "text": updated_text}],
        },
    )
    assert response.status_code == 200, response.text

    recipe_detail = client.get(f"/api/v1/recipes/{recipe['id']}").json()
    assert recipe_detail["custom_instructions"] == updated_text
    reloaded = client.get(f"/api/v1/recipes/{recipe['id']}/method").json()
    assert reloaded["source_blocks"][0]["text"] == updated_text


def test_recipe_editor_api_rejects_custom_instruction_changes_when_method_snapshot_exists(
    client, owner, session_factory
):
    recipe = _custom_recipe(client, owner, "Fry the zucchini until tender.")
    ingredient = recipe["ingredients"][0]
    editor_payload = {
        "expected_version": recipe["version"],
        "title": recipe["title"],
        "yield_servings": recipe["yield_servings"],
        "meal_types": recipe["meal_types"],
        "custom_instructions": "Bake the zucchini instead.",
        "ingredients": [{
            "lineage_id": ingredient["lineage_id"],
            "original_text": ingredient["original_text"],
            "quantity": ingredient["quantity"],
            "unit": ingredient["unit"],
            "food_phrase": ingredient["food_phrase"],
            "included": ingredient["included"],
        }],
    }

    editor_update = client.put(
        f"/api/v1/recipes/{recipe['id']}",
        headers=_headers(owner),
        json=editor_payload,
    )
    assert editor_update.status_code == 409
    assert editor_update.json()["code"] == "METHOD_EDITOR_REQUIRED"

    review_update = client.put(
        f"/api/v1/recipes/{recipe['id']}/review",
        headers=_headers(owner),
        json=editor_payload,
    )
    assert review_update.status_code == 409
    assert review_update.json()["code"] == "METHOD_EDITOR_REQUIRED"

    with session_factory() as db:
        from app.models import RecipeMethodSnapshot, RecipeVersion

        versions = db.scalars(
            select(RecipeVersion)
            .where(RecipeVersion.recipe_id == recipe["id"])
            .order_by(RecipeVersion.version_number)
        ).all()
        assert len(versions) == 1
        snapshot = db.scalar(
            select(RecipeMethodSnapshot).where(
                RecipeMethodSnapshot.recipe_version_id == versions[0].id
            )
        )
        assert snapshot is not None
        assert snapshot.source_text == "Fry the zucchini until tender."


def test_custom_method_without_a_snapshot_is_repaired_from_submitted_instructions(
    client, owner, session_factory
):
    recipe = _custom_recipe(client, owner, "Fry the zucchini until tender.")
    with session_factory() as db:
        from app.models import RecipeMethodSnapshot, RecipeVersion

        version = db.scalar(select(RecipeVersion).where(RecipeVersion.recipe_id == recipe["id"]))
        assert version is not None
        snapshot = db.scalar(
            select(RecipeMethodSnapshot).where(RecipeMethodSnapshot.recipe_version_id == version.id)
        )
        assert snapshot is not None
        db.delete(snapshot)
        db.commit()

    response = client.get(f"/api/v1/recipes/{recipe['id']}/method")
    assert response.status_code == 200, response.text
    assert response.json()["source_blocks"][0]["text"] == "Fry the zucchini until tender."

    with session_factory() as db:
        from app.models import RecipeMethodSnapshot, RecipeVersion

        version = db.scalar(select(RecipeVersion).where(RecipeVersion.recipe_id == recipe["id"]))
        assert version is not None
        assert db.scalar(
            select(RecipeMethodSnapshot).where(RecipeMethodSnapshot.recipe_version_id == version.id)
        ) is not None


def test_batch_method_scales_custom_recipe_ingredients_to_planned_servings(
    client, owner, session_factory
):
    recipe = _custom_recipe(client, owner)
    with session_factory() as db:
        from app.models import Household, MealBatch, MealPlan, RecipeVersion

        household = db.scalar(select(Household))
        version = db.scalar(select(RecipeVersion).where(RecipeVersion.recipe_id == recipe["id"]))
        assert household is not None
        assert version is not None
        plan = MealPlan(
            household_id=household.id,
            name="Week",
            start_date=date(2026, 8, 24),
            end_date=date(2026, 8, 30),
        )
        db.add(plan)
        db.flush()
        batch = MealBatch(
            meal_plan_id=plan.id,
            recipe_version_id=version.id,
            servings=8,
            planned_cook_date=plan.start_date,
        )
        db.add(batch)
        db.commit()
        batch_id = batch.id

    response = client.get(f"/api/v1/recipes/{recipe['id']}/method?batch_id={batch_id}")
    assert response.status_code == 200, response.text
    method = response.json()
    assert method["batch_context"]["servings"] == 8
    assert method["requested_servings"] == "8.00"
    assert method["ingredients"][0]["quantity_text"] == "4"


def test_cooked_historical_batch_can_capture_the_current_method(
    client, owner, session_factory
):
    recipe = _custom_recipe(client, owner, "Fry the zucchini in a pan for 5 minutes.")
    initial = client.get(f"/api/v1/recipes/{recipe['id']}/method").json()
    updated_text = "Cook the zucchini gently in a pan for 7 minutes."
    updated = client.put(
        f"/api/v1/recipes/{recipe['id']}/method",
        headers=_headers(owner),
        json={
            "expected_version": initial["recipe_version"],
            "method": initial["method"],
            "mark_reviewed": True,
            "source_kind": "custom",
            "source_blocks": [{**initial["source_blocks"][0], "text": updated_text}],
        },
    )
    assert updated.status_code == 200, updated.text

    with session_factory() as db:
        from app.models import Household, MealBatch, MealPlan, RecipeMethodSnapshot, RecipeVersion

        household = db.scalar(select(Household))
        versions = db.scalars(
            select(RecipeVersion)
            .where(RecipeVersion.recipe_id == recipe["id"])
            .order_by(RecipeVersion.version_number)
        ).all()
        assert len(versions) == 2
        assert household is not None
        historical, latest = versions
        old_snapshot = db.scalar(
            select(RecipeMethodSnapshot).where(
                RecipeMethodSnapshot.recipe_version_id == historical.id
            )
        )
        assert old_snapshot is not None
        historical.custom_instructions = None
        db.delete(old_snapshot)
        plan = MealPlan(
            household_id=household.id,
            name="Historical recovery",
            start_date=date(2026, 8, 24),
            end_date=date(2026, 8, 30),
        )
        db.add(plan)
        db.flush()
        batch = MealBatch(
            meal_plan_id=plan.id,
            recipe_version_id=historical.id,
            servings=8,
            planned_cook_date=plan.start_date,
            cooked_at=datetime.now(timezone.utc),
        )
        db.add(batch)
        db.commit()
        batch_id = batch.id
        historical_id = historical.id
        latest_id = latest.id

    missing = client.get(f"/api/v1/recipes/{recipe['id']}/method?batch_id={batch_id}")
    assert missing.status_code == 409, missing.text
    assert missing.json()["code"] == "HISTORICAL_METHOD_NOT_CAPTURED"
    assert missing.json()["actions"][0] == {
        "kind": "recover_historical_method",
        "label": "Use current method for this batch",
        "recipe_id": recipe["id"],
        "batch_id": batch_id,
        "suggestion": (
            "This copies the current saved method onto the historical batch so it can be "
            "scaled. The cooked record and batch ingredients stay unchanged."
        ),
    }

    recovered = client.post(
        f"/api/v1/recipes/{recipe['id']}/method/recover-historical?batch_id={batch_id}",
        headers=_headers(owner),
    )
    assert recovered.status_code == 200, recovered.text
    method = recovered.json()
    assert method["source_blocks"][0]["text"] == updated_text
    assert method["requested_servings"] == "8.00"
    assert method["ingredients"][0]["quantity_text"] == "4"

    with session_factory() as db:
        from app.models import MealBatch, RecipeMethodSnapshot

        batch = db.get(MealBatch, batch_id)
        assert batch is not None
        assert batch.recipe_version_id == historical_id
        assert batch.recipe_version_id != latest_id
        assert db.scalar(
            select(RecipeMethodSnapshot).where(
                RecipeMethodSnapshot.recipe_version_id == historical_id
            )
        ) is not None


def test_unaccounted_clause_warns_but_does_not_block_review_or_persistence(client, owner):
    recipe = _custom_recipe(
        client,
        owner,
        "Fry the zucchini in a pan for 5 minutes. The sauce becomes glossy.",
    )
    response = client.get(f"/api/v1/recipes/{recipe['id']}/method")
    assert response.status_code == 200, response.text
    method = response.json()
    assert method["coverage"]["unreviewed"] == 1

    document = MethodDocument.model_validate(method["method"])
    document.actions[0].text = "Gently fry the courgette"
    reviewed_response = client.put(
        f"/api/v1/recipes/{recipe['id']}/method",
        headers=_headers(owner),
        json={
            "expected_version": method["recipe_version"],
            "method": document.model_dump(mode="json"),
            "household_notes": "Use the heavy pan.",
            "mark_reviewed": True,
            "source_kind": "custom",
            "source_blocks": method["source_blocks"],
        },
    )

    assert reviewed_response.status_code == 200, reviewed_response.text
    reviewed = reviewed_response.json()
    assert reviewed["method_status"] == "reviewed"
    assert reviewed["coverage"]["unreviewed"] == 1
    assert reviewed["method"]["actions"][0]["text"] == "Gently fry the courgette"
    assert reviewed["household_notes"] == "Use the heavy pan."

    reloaded_response = client.get(f"/api/v1/recipes/{recipe['id']}/method")
    assert reloaded_response.status_code == 200, reloaded_response.text
    reloaded = reloaded_response.json()
    assert reloaded["method_status"] == "reviewed"
    assert reloaded["coverage"]["unreviewed"] == 1
    assert reloaded["method"]["actions"][0]["text"] == "Gently fry the courgette"
    assert reloaded["household_notes"] == "Use the heavy pan."


def test_manual_word_link_renders_the_full_ingredient_amount(client, owner):
    create_response = client.post(
        "/api/v1/recipes",
        headers=_headers(owner),
        json={
            "title": "Red onion supper",
            "source_type": "custom",
            "yield_servings": 2,
            "custom_instructions": "Fry the onions until soft.",
            "meal_types": ["dinner"],
            "ingredients": [
                {
                    "original_text": "2 red onions",
                    "quantity": 2,
                    "unit": "item",
                    "food_phrase": "red onions",
                    "included": True,
                }
            ],
        },
    )
    assert create_response.status_code == 201, create_response.text
    recipe = create_response.json()

    method_response = client.get(f"/api/v1/recipes/{recipe['id']}/method")
    assert method_response.status_code == 200, method_response.text
    method = method_response.json()
    source = method["source_blocks"][0]["text"]
    word_start = source.index("onions")
    lineage_id = method["ingredients"][0]["lineage_id"]
    action_id = method["method"]["actions"][0]["id"]

    document = method["method"]
    document["annotations"] = [
        annotation
        for annotation in document["annotations"]
        if annotation["kind"] != "ingredient"
    ]
    document["ingredient_bindings"] = []
    document["annotations"].append(
        {
            "id": "manual-red-onion-word",
            "block_id": method["source_blocks"][0]["id"],
            "start": word_start,
            "end": word_start + len("onions"),
            "kind": "ingredient",
            "origin": "user",
            "confidence": 1,
            "accepted": True,
            "ingredient_lineage_id": lineage_id,
        }
    )
    document["ingredient_bindings"].append(
        {
            "id": "manual-red-onion-binding",
            "action_id": action_id,
            "ingredient_lineage_id": lineage_id,
            "annotation_id": "manual-red-onion-word",
            "portion_mode": "unspecified",
            "confidence": 1,
            "accepted": True,
        }
    )

    save_response = client.put(
        f"/api/v1/recipes/{recipe['id']}/method",
        headers=_headers(owner),
        json={
            "expected_version": method["recipe_version"],
            "method": document,
            "mark_reviewed": False,
            "source_kind": "custom",
            "source_blocks": method["source_blocks"],
        },
    )
    assert save_response.status_code == 200, save_response.text
    ingredient_segments = [
        segment
        for block in save_response.json()["rendered_blocks"]
        for segment in block["segments"]
        if segment["kind"] == "ingredient"
    ]
    assert ingredient_segments == [
        {
            "kind": "ingredient",
            "text": "onions",
            "annotation_id": "manual-red-onion-word",
            "ingredient_lineage_id": lineage_id,
            "quantity_label": "2 item red onions",
        }
    ]


def test_method_preferences_are_user_scoped_and_partially_update(client, owner):
    response = client.patch(
        "/api/v1/auth/me",
        headers=_headers(owner),
        json={
            "method_view_preference": "written",
            "measurement_system": "metric",
            "method_tutorial_version_seen": 1,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["ingredient_locale"] == "uk"
    assert response.json()["method_view_preference"] == "written"
    assert response.json()["measurement_system"] == "metric"
    assert response.json()["method_tutorial_version_seen"] == 1


def test_method_document_rejects_edges_to_unknown_actions():
    try:
        MethodDocument.model_validate(
            {
                "schema_version": 1,
                "stages": [{"id": "stage-1", "title": "Method", "position": 0}],
                "actions": [],
                "edges": [
                    {
                        "id": "edge-1",
                        "from_action_id": "missing-a",
                        "to_action_id": "missing-b",
                        "kind": "sequence",
                    }
                ],
            }
        )
    except ValueError as exc:
        assert "existing actions" in str(exc)
    else:
        raise AssertionError("invalid graph was accepted")
