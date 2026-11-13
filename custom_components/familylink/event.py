"""Event entity per child: an app's usage grew (see usage_tracker.py)."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, LOGGER_NAME
from .coordinator import FamilyLinkDataUpdateCoordinator
from .devices import ensure_child_device

_LOGGER = logging.getLogger(LOGGER_NAME)

EVENT_USAGE_GREW = "usage_grew"


async def async_setup_entry(
	hass: HomeAssistant,
	entry: ConfigEntry,
	async_add_entities: AddEntitiesCallback,
) -> None:
	"""One app usage event entity per child."""
	coordinator = hass.data[DOMAIN][entry.entry_id]
	entities = []
	for child_data in (coordinator.data or {}).get("children_data", []):
		ensure_child_device(hass, coordinator, entry.entry_id, child_data["child_id"], child_data["child_name"])
		entities.append(FamilyLinkAppUsageEvent(coordinator, child_data["child_id"], child_data["child_name"]))
	async_add_entities(entities)


class FamilyLinkAppUsageEvent(CoordinatorEntity, EventEntity):
	"""Fires `usage_grew` for each app and device whose usage grew since the last refresh.

	The event data: package, app (its name), device, grew_minutes, today_minutes
	and reported_at (when Google received the usage; the use happened before).
	Each refresh's events fire once, also when the coordinator hands the same
	data to its listeners again.
	"""

	_attr_has_entity_name = True
	_attr_name = "App usage"
	_attr_icon = "mdi:cellphone-play"
	_attr_event_types = [EVENT_USAGE_GREW]

	def __init__(self, coordinator: FamilyLinkDataUpdateCoordinator, child_id: str, child_name: str) -> None:
		"""Initialize the entity."""
		super().__init__(coordinator)
		self._child_id = child_id
		self._child_name = child_name
		self._attr_unique_id = f"{DOMAIN}_{child_id}_app_usage_event"
		# The refresh whose events fired last; the one at setup is not news
		self._fired_refresh = self._child_data().get("usage_refresh")

	@property
	def device_info(self) -> DeviceInfo:
		"""The child's hub."""
		return DeviceInfo(
			identifiers={(DOMAIN, self._child_id)},
			name=f"{self._child_name} (Family Link)",
			manufacturer="Google",
			model="Family Link Account",
		)

	def _child_data(self) -> dict[str, Any]:
		for child_data in (self.coordinator.data or {}).get("children_data", []):
			if child_data.get("child_id") == self._child_id:
				return child_data
		return {}

	@callback
	def _handle_coordinator_update(self) -> None:
		child_data = self._child_data()
		refresh = child_data.get("usage_refresh")
		if refresh is None or refresh == self._fired_refresh:
			return
		self._fired_refresh = refresh
		titles = {app.get("packageName"): app.get("title") for app in child_data.get("apps", [])}
		for grew in child_data.get("usage_grew") or []:
			self._trigger_event(EVENT_USAGE_GREW, {"app": titles.get(grew["package"]) or grew["package"], **grew})
			self.async_write_ha_state()
