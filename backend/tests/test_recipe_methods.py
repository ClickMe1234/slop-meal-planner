from decimal import Decimal

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
