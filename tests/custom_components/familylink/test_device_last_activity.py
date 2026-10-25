"""When Google last heard from a device."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import EntityCategory

from custom_components.familylink.sensor import FamilyLinkDeviceLastActivitySensor


def _sensor(devices: list) -> FamilyLinkDeviceLastActivitySensor:
    coordinator = SimpleNamespace(
        data={"children_data": [{"child_id": "1001", "child_name": "Alex", "devices": devices}]},
        child_device_ids={},
        last_update_success=True,
    )
    return FamilyLinkDeviceLastActivitySensor(coordinator, "1001", "Alex", "dev-phone", "Pixel 9 Pro")


def test_the_last_check_in_is_a_timestamp():
    sensor = _sensor([{"id": "dev-phone", "last_activity": "1791633600000"}])

    assert sensor.native_value == datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
    assert sensor.device_class == SensorDeviceClass.TIMESTAMP
    assert sensor.entity_category == EntityCategory.DIAGNOSTIC
    assert sensor.unique_id == "familylink_1001_dev-phone_last_activity"
    assert sensor.has_entity_name
    assert sensor.name == "Last Activity"


def test_no_or_unreadable_time_reads_unknown_and_a_missing_device_unavailable():
    assert _sensor([{"id": "dev-phone"}]).native_value is None
    assert _sensor([{"id": "dev-phone", "last_activity": "soon"}]).native_value is None

    gone = _sensor([])
    assert gone.native_value is None
    assert not gone.available
