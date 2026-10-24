"""Select platform for Google Family Link integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .client.api import FamilyLinkClient
from .const import DOMAIN, LOGGER_NAME
from .coordinator import FamilyLinkDataUpdateCoordinator
from .devices import ensure_child_device

_LOGGER = logging.getLogger(LOGGER_NAME)

# Restriction levels of the trustedcontacts endpoint. 0 is what an account
# returns before the setting has ever been touched (captured live 2026-08-26)
# and behaves like 1, so both map to "Anyone".
OPTION_ANYONE = "Anyone"
OPTION_CONTACTS_ONLY = "Only contacts I add"
OPTION_CONTACTS_AND_GROUPS = "Contacts I add & limited groups"

OPTION_TO_LEVEL = {
    OPTION_ANYONE: 1,
    OPTION_CONTACTS_ONLY: 3,
    OPTION_CONTACTS_AND_GROUPS: 4,
}
LEVEL_TO_OPTION = {0: OPTION_ANYONE, **{level: option for option, level in OPTION_TO_LEVEL.items()}}

# Chrome filter modes, worded as in the Family Link app, and the filterLevel
# names websites:listRestrictions gives them back with
OPTION_ALL_SITES = "Allow all sites"
OPTION_BLOCK_EXPLICIT = "Try to block explicit sites"
OPTION_APPROVED_ONLY = "Only allow approved sites"

WEB_FILTER_OPTION_TO_MODE = {
    OPTION_ALL_SITES: FamilyLinkClient.WEB_FILTER_ALL_SITES,
    OPTION_BLOCK_EXPLICIT: FamilyLinkClient.WEB_FILTER_BLOCK_EXPLICIT,
    OPTION_APPROVED_ONLY: FamilyLinkClient.WEB_FILTER_APPROVED_ONLY,
}
FILTER_LEVEL_TO_OPTION = {
    "safeSites": OPTION_BLOCK_EXPLICIT,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Family Link select platform."""
    coordinator: FamilyLinkDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    if not coordinator.data or "children_data" not in coordinator.data:
        _LOGGER.error("No children data in coordinator after first refresh")
        return

    for child_data in coordinator.data.get("children_data", []):
        ensure_child_device(hass, coordinator, entry.entry_id, child_data["child_id"], child_data["child_name"])

    entities: list[SelectEntity] = []
    for child_data in coordinator.data.get("children_data", []):
        entities.append(
            FamilyLinkContactRestrictionSelect(
                coordinator, child_data["child_id"], child_data["child_name"]
            )
        )
        entities.append(
            FamilyLinkWebFilterSelect(
                coordinator, child_data["child_id"], child_data["child_name"]
            )
        )
    async_add_entities(entities)


class FamilyLinkContactRestrictionSelect(CoordinatorEntity, SelectEntity):
    """Who can call and text the child (Family Link "Allowed calls and texts").

    The level is fetched by the coordinator with the other per-child data, so
    this entity only reads coordinator.data like the rest of the platform and
    benefits from its cache fallback and session-expiry handling.
    """

    _attr_options = list(OPTION_TO_LEVEL)
    _attr_icon = "mdi:phone-lock"

    def __init__(
        self,
        coordinator: FamilyLinkDataUpdateCoordinator,
        child_id: str,
        child_name: str,
    ) -> None:
        """Initialize the select entity."""
        super().__init__(coordinator)
        self._child_id = child_id
        self._child_name = child_name
        self._attr_name = f"{child_name} Allowed Calls & Texts"
        self._attr_unique_id = f"{DOMAIN}_{child_id}_allowed_calls_texts"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information for this child."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._child_id)},
            name=f"{self._child_name} (Family Link)",
            manufacturer="Google",
            model="Family Link Account",
        )

    def _get_child_data(self) -> dict[str, Any] | None:
        """Get coordinator data for this child."""
        if not self.coordinator.data or "children_data" not in self.coordinator.data:
            return None
        for child_data in self.coordinator.data["children_data"]:
            if child_data["child_id"] == self._child_id:
                return child_data
        return None

    @property
    def current_option(self) -> str | None:
        """Return the option matching the level last read by the coordinator."""
        child_data = self._get_child_data()
        if not child_data:
            return None
        level = child_data.get("contact_restriction")
        if level is None:
            return None
        option = LEVEL_TO_OPTION.get(level)
        if option is None:
            _LOGGER.debug(
                f"Unknown contact restriction level {level} for {self._child_name}"
            )
        return option

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the child ids so services can target this child."""
        attributes: dict[str, Any] = {
            "child_id": self._child_id,
            "child_name": self._child_name,
        }
        child_data = self._get_child_data()
        if child_data:
            attributes["restriction_level"] = child_data.get("contact_restriction")
        return attributes

    async def async_select_option(self, option: str) -> None:
        """Change who can call and text the child."""
        level = OPTION_TO_LEVEL[option]
        success = await self.coordinator.client.async_set_contact_restriction(
            level, account_id=self._child_id
        )
        if not success:
            _LOGGER.error(
                f"Failed to set allowed calls and texts to '{option}' for {self._child_name}"
            )
            return
        _LOGGER.info(f"Set allowed calls and texts to '{option}' for {self._child_name}")
        await self.coordinator.async_request_refresh()


class FamilyLinkWebFilterSelect(FamilyLinkContactRestrictionSelect):
    """The child's Chrome filter mode (Family Link "Google Chrome and Web").

    The mode comes with the site lists the coordinator reads every
    WEBSITES_REFRESH seconds, so the entity is unavailable until they have
    been read (an account without Chrome never has them). A change made here
    is read back at once.
    """

    _attr_options = list(WEB_FILTER_OPTION_TO_MODE)
    _attr_icon = "mdi:web"

    def __init__(
        self,
        coordinator: FamilyLinkDataUpdateCoordinator,
        child_id: str,
        child_name: str,
    ) -> None:
        """Initialize the select entity."""
        super().__init__(coordinator, child_id, child_name)
        self._attr_name = f"{child_name} Web Filter"
        self._attr_unique_id = f"{DOMAIN}_{child_id}_web_filter"

    def _websites(self) -> dict[str, Any] | None:
        child_data = self._get_child_data()
        return child_data.get("websites") if child_data else None

    @property
    def available(self) -> bool:
        """Available once the site lists have been read."""
        return self.coordinator.last_update_success and self._websites() is not None

    @property
    def current_option(self) -> str | None:
        """Return the option matching the filter level last read."""
        level = (self._websites() or {}).get("filter_level")
        option = FILTER_LEVEL_TO_OPTION.get(level)
        if level is not None and option is None:
            _LOGGER.debug(f"Unknown Chrome filter level {level} for {self._child_name}")
        return option

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The child ids and the filter level as Google names it."""
        return {
            "child_id": self._child_id,
            "child_name": self._child_name,
            "filter_level": (self._websites() or {}).get("filter_level"),
        }

    async def async_select_option(self, option: str) -> None:
        """Change the Chrome filter mode, then read it back."""
        client = self.coordinator.client
        try:
            await client.async_set_web_filter(self._child_id, WEB_FILTER_OPTION_TO_MODE[option])
        except Exception as err:
            raise HomeAssistantError(f"Setting the web filter for {self._child_name} failed: {err}") from err
        _LOGGER.info(f"Set the web filter to '{option}' for {self._child_name}")
        try:
            self.coordinator.store_websites(self._child_id, await client.async_get_website_restrictions(self._child_id))
        except Exception as err:
            # The change was made; the mode shows at the next read of the lists
            _LOGGER.debug(f"Reading the site lists back for {self._child_name} failed: {err}")
        await self.coordinator.async_request_refresh()
