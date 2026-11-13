"""A child with no device sharing location: no location, and no warning on every poll."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

from custom_components.familylink.client.api import FamilyLinkClient

CHILD = "123456789012345678901"


def _client(hass, payload) -> FamilyLinkClient:
    client = FamilyLinkClient(hass, {})
    response = MagicMock(status=200)
    response.json = AsyncMock(return_value=payload)
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=response)
    context.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.get = MagicMock(return_value=context)
    client._get_session = AsyncMock(return_value=session)
    client._get_cookie_header = MagicMock(return_value="SAPISID=x")
    client.is_authenticated = MagicMock(return_value=True)
    return client


async def test_no_shared_location_is_none_without_a_warning(hass, caplog):
    # The live answer for a child without a location device: the location slot is null
    client = _client(hass, [[None, "1791757841976"], [CHILD, 2, None, None, 0]])

    with caplog.at_level(logging.DEBUG, logger="custom_components.familylink"):
        assert await client.async_get_location(account_id=CHILD) is None

    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert "No location shared" in caplog.text


async def test_a_malformed_location_still_warns(hass, caplog):
    client = _client(hass, [[None, "1791757841976"], [CHILD, 2, ["not-a-location"], None, 0]])

    with caplog.at_level(logging.WARNING, logger="custom_components.familylink"):
        assert await client.async_get_location(account_id=CHILD) is None

    assert "Invalid location array" in caplog.text
