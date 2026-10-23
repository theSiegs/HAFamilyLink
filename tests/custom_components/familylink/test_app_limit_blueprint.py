"""The blueprint that blocks an app after some minutes a day loads and fills in."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components.automation.config import async_validate_config_item
from homeassistant.components.blueprint import BlueprintInputs
from homeassistant.components.blueprint.models import Blueprint
from homeassistant.components.blueprint.schemas import BLUEPRINT_SCHEMA
from homeassistant.util.yaml import load_yaml

BLUEPRINT = Path(__file__).parents[3] / "blueprints/automation/familylink/block_app_after_daily_minutes.yaml"


def _blueprint() -> Blueprint:
    return Blueprint(load_yaml(BLUEPRINT), expected_domain="automation", path=BLUEPRINT.name, schema=BLUEPRINT_SCHEMA)


def test_the_blueprint_asks_for_the_sensor_the_minutes_and_the_unblock_time():
    blueprint = _blueprint()

    assert set(blueprint.inputs) == {"usage_sensor", "minutes", "unblock_at"}
    assert blueprint.inputs["minutes"]["default"] == 60


async def test_an_automation_from_the_blueprint_is_valid(hass):
    inputs = BlueprintInputs(
        _blueprint(),
        {
            "use_blueprint": {
                "path": BLUEPRINT.name,
                "input": {"usage_sensor": "sensor.lounge_tv_alex_video_usage_today", "minutes": 45},
            }
        },
    )
    config = inputs.async_substitute()

    assert config["triggers"][0]["above"] == 45
    assert config["triggers"][2]["at"] == "06:00:00"
    assert config["variables"]["usage_sensor"] == "sensor.lounge_tv_alex_video_usage_today"
    validated = await async_validate_config_item(hass, "test", config)
    assert validated is not None
    assert getattr(validated, "validation_error", None) is None
