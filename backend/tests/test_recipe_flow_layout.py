import json
from pathlib import Path

from app.services.recipe_flow_layout import layout_flow_table


FIXTURE = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "fixtures" / "recipe_flow_layout.json"


def test_python_layout_matches_shared_typescript_fixture():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert layout_flow_table(fixture["method"], fixture["table"]) == fixture["expected"]
