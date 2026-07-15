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


def test_preparation_adjectives_and_commas_do_not_replace_the_ingredient_name():
    assert parse_ingredient("cubed courgette").food_phrase == "courgette"

    chicken = parse_ingredient("skinless, boneless chicken thighs")
    assert chicken.food_phrase == "chicken thighs"
    assert chicken.preparation == "skinless boneless"
    assert chicken.needs_review is False

    tomatoes = parse_ingredient("400g chopped tomatoes")
    assert tomatoes.food_phrase == "tomatoes"
    assert tomatoes.preparation == "chopped"

    parsley = parse_ingredient("roughly chopped fresh parsley")
    assert parsley.food_phrase == "fresh parsley"
    assert parsley.preparation == "roughly chopped"


def test_descriptive_herb_amounts_are_quantities_not_names():
    handful = parse_ingredient("a handful of mint")
    assert handful.quantity == Decimal("1")
    assert handful.unit == "handful"
    assert handful.food_phrase == "mint"
    assert handful.needs_review is False

    sprig = parse_ingredient("a sprig of thyme")
    assert sprig.quantity == Decimal("1")
    assert sprig.unit == "sprig"
    assert sprig.food_phrase == "thyme"
    assert sprig.needs_review is False


def test_multiple_ingredient_names_are_retained_and_flagged_for_confirmation():
    seasoning = parse_ingredient("salt and pepper to taste")
    assert seasoning.food_phrase == "salt and pepper"
    assert seasoning.needs_review is True
