from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET


TEMPLATE = Path(__file__).resolve().parents[2] / "deploy" / "unraid-template.xml"


def test_unraid_template_matches_production_runtime_contract():
    root = ET.parse(TEMPLATE).getroot()
    configs = {config.attrib["Target"]: config for config in root.findall("Config")}

    assert root.findtext("Name") == "Slop Meal Planner"
    assert root.findtext("Repository") == "ghcr.io/clickme1234/slop-meal-planner:1.3.2"
    assert root.findtext("Network") == "Bridge"
    assert root.findtext("PostArgs") == ""
    assert root.findtext("WebUI") == "https://[IP]:[PORT:8000]/"
    assert "--read-only" in (root.findtext("ExtraParams") or "")
    assert "--security-opt no-new-privileges" in (root.findtext("ExtraParams") or "")
    assert root.findtext("Privileged") == "false"

    assert configs["8000"].attrib["Type"] == "Port"
    assert configs["8000"].attrib["Default"] == "8080"
    assert configs["/data"].attrib["Mode"] == "rw"
    assert configs["/backups"].attrib["Mode"] == "rw"
    assert configs["/data"].attrib["Default"].endswith("/slop-meal-planner/data")
    assert configs["/backups"].attrib["Default"].endswith("/slop-meal-planner")

    for required in (
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "REDIS_HOST",
        "REDIS_PORT",
        "MEAL_PLANNER_SECRET_KEY",
        "MEAL_PLANNER_SETUP_TOKEN",
        "MEAL_PLANNER_ALLOWED_HOSTS",
        "MEAL_PLANNER_COOKIE_SECURE",
        "MEAL_PLANNER_HSTS_ENABLED",
        "TZ",
        "PUID",
        "PGID",
    ):
        assert required in configs

    assert configs["POSTGRES_PASSWORD"].attrib["Mask"] == "true"
    assert configs["REDIS_PASSWORD"].attrib["Mask"] == "true"
    assert configs["MEAL_PLANNER_DATABASE_URL"].attrib["Display"] == "advanced"
    assert configs["CELERY_BROKER_URL"].attrib["Display"] == "advanced"
    assert configs["CELERY_RESULT_BACKEND"].attrib["Display"] == "advanced"
