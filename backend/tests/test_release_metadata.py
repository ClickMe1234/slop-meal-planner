from __future__ import annotations

import json
from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[2]


def test_release_metadata_uses_the_version_file_as_its_single_source_of_truth():
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    package = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    lockfile = json.loads((ROOT / "frontend" / "package-lock.json").read_text(encoding="utf-8"))
    project = tomllib.loads((ROOT / "backend" / "pyproject.toml").read_text(encoding="utf-8"))

    assert package["version"] == version
    assert lockfile["version"] == version
    assert lockfile["packages"][""]["version"] == version
    assert project["project"]["version"] == version

    expected_image = f"ghcr.io/clickme1234/slop-meal-planner:{version}"
    unraid_template = (ROOT / "deploy" / "unraid-template.xml").read_text(encoding="utf-8")
    deployment_readme = (ROOT / "deploy" / "README.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"<Repository>{expected_image}</Repository>" in unraid_template
    assert f"| Repository | `{expected_image}` |" in deployment_readme
    assert f"`{expected_image}` is public" in deployment_readme
    assert f"`{expected_image}` as Repository" in readme
    assert f"Current release: **{version}**" in readme
    assert f"## {version} - " in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    for path in (ROOT / "backend" / "app" / "main.py", ROOT / "backend" / "app" / "config.py", ROOT / "backend" / "app" / "services" / "food_search.py"):
        assert version in path.read_text(encoding="utf-8")
