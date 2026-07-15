from decimal import Decimal

from app.services.ingredients import food_search_phrase, parse_ingredient


def test_recipe_units_and_food_phrases_are_detected_without_inventing_weights():
    multipack = parse_ingredient("2 x 400g cans chickpeas, drained")
    assert multipack.quantity == Decimal("2")
    assert multipack.unit == "can"
    assert multipack.quantity_grams == Decimal("800")
    assert multipack.food_phrase == "chickpeas"
    assert multipack.preparation == "drained"
    assert multipack.quantity_calculated is True

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


def test_package_arithmetic_uses_the_total_weight_and_keeps_the_package_unit():
    delight = parse_ingredient(
        "2 x 55g bars Turkish delight halved and sliced "
        "(or use Maltesers, Milky Way or Crunchie bars)"
    )

    assert delight.quantity == Decimal("2")
    assert delight.unit == "bar"
    assert delight.quantity_grams == Decimal("110")
    assert delight.food_phrase == "Turkish delight"
    assert delight.preparation == "halved and sliced"
    assert delight.quantity_calculated is True

    loose_volume = parse_ingredient("2 × 500 ml coconut milk")
    assert loose_volume.quantity == Decimal("1000")
    assert loose_volume.unit == "ml"
    assert loose_volume.quantity_grams is None

    bottles = parse_ingredient("3 x 200 ml bottles coconut milk")
    assert bottles.quantity == Decimal("3")
    assert bottles.unit == "bottle"

    nested_count = parse_ingredient("2 x 6 chicken breasts")
    assert nested_count.quantity == Decimal("12")
    assert nested_count.unit == "item"


def test_fractional_food_portions_are_converted_to_whole_items():
    chicken = parse_ingredient(
        "4 skinless, boneless chicken breast halves - cooked and diced"
    )

    assert chicken.quantity == Decimal("2")
    assert chicken.unit == "item"
    assert chicken.quantity_grams is None
    assert chicken.food_phrase == "chicken breasts"
    assert chicken.preparation == "skinless boneless, cooked and diced"
    assert chicken.quantity_calculated is True

    potatoes = parse_ingredient("8 potato quarters")
    assert potatoes.quantity == Decimal("2")
    assert potatoes.food_phrase == "potatoes"

    mass = parse_ingredient(
        "1 pound skinless, boneless chicken breast halves - cut into 1 inch cubes"
    )
    assert mass.quantity == Decimal("1")
    assert mass.unit == "lb"
    assert mass.quantity_grams == Decimal("453.59237")
    assert mass.food_phrase == "chicken breasts"
    assert mass.quantity_calculated is False

    prepared = parse_ingredient("2 onions, halved")
    assert prepared.quantity == Decimal("2")
    assert prepared.food_phrase == "onions"
    assert prepared.quantity_calculated is False


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
