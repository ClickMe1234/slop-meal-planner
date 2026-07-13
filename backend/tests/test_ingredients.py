from decimal import Decimal

from app.services.ingredients import food_search_phrase, parse_ingredient


def test_recipe_units_and_food_phrases_are_detected_without_inventing_weights():
    multipack = parse_ingredient("2 x 400g cans chickpeas, drained")
    assert multipack.quantity == Decimal("2")
    assert multipack.unit == "can"
    assert multipack.quantity_grams == Decimal("800")
    assert multipack.food_phrase == "chickpeas"
    assert multipack.preparation == "drained"

    tablespoon = parse_ingredient("2 tbsp rose harissa")
    assert tablespoon.quantity == Decimal("2")
    assert tablespoon.unit == "tbsp"
    assert tablespoon.quantity_grams is None
    assert tablespoon.food_phrase == "rose harissa"

    clove = parse_ingredient("3 cloves garlic, crushed")
    assert clove.unit == "clove"
    assert clove.food_phrase == "garlic"

    sized = parse_ingredient("1 large onion, chopped")
    assert sized.unit == "large"
    assert sized.food_phrase == "onion"

    fraction = parse_ingredient("½ tsp salt")
    assert fraction.quantity == Decimal("0.5")
    assert fraction.unit == "tsp"


def test_food_search_uses_plain_ingredient_phrase():
    assert food_search_phrase("2 x 400g cans chickpeas, drained") == "chickpeas"
    assert food_search_phrase("3 cloves garlic, crushed") == "garlic"
