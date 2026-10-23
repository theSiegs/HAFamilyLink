"""Which apps get their own usage sensor.

A sensor per app and day is what the usage-by-hour graph needs: Home Assistant's
long-term statistics turn the minutes used so far today into minutes added per
hour. Google only gives a daily total per app and device, so the hours are the
ones Google received the usage in (a phone uploads about every 5 minutes, a
tablet every 15 to 20).

Every installed app would be 150 or more sensors per child, so each child gets
the apps used most over the days Google returned (up to 30), and each device
that takes no time limits (a Google TV or streamer, a watch) the apps used most
on it. That is how those are told apart from a phone or tablet; their apps are
tracked on their own because they are not the apps of the phone and nothing
else limits them. Launchers and system screens are left out of the ranking;
the options set the counts and the apps always or never given a sensor.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import re
from typing import Any

from .const import (
	CONF_APP_USAGE_EXCLUDED,
	CONF_APP_USAGE_PER_CHILD,
	CONF_APP_USAGE_PER_DEVICE,
	CONF_APP_USAGE_PINNED,
	DEFAULT_APP_USAGE_PER_CHILD,
	DEFAULT_APP_USAGE_PER_DEVICE,
	DOMAIN,
)

# An app with less than this over the returned days is not worth a sensor
MIN_RANKED_SECONDS = 600
# Screens the child passes through rather than uses: never ranked
_SYSTEM_PACKAGES = frozenset({
	"com.android.systemui",
	"com.android.permissioncontroller",
	"com.google.android.permissioncontroller",
})


@dataclass(frozen=True)
class AppUsageSettings:
	"""The options of the app usage sensors."""

	per_child: int = DEFAULT_APP_USAGE_PER_CHILD
	per_device: int = DEFAULT_APP_USAGE_PER_DEVICE
	pinned: frozenset[str] = field(default_factory=frozenset)
	excluded: frozenset[str] = field(default_factory=frozenset)

	@classmethod
	def from_options(cls, options: Mapping[str, Any]) -> AppUsageSettings:
		"""Read the options; a missing one keeps the default."""
		def packages(key: str) -> frozenset[str]:
			return frozenset(p.strip() for p in options.get(key) or [] if p and p.strip())

		return cls(
			per_child=int(options.get(CONF_APP_USAGE_PER_CHILD, DEFAULT_APP_USAGE_PER_CHILD)),
			per_device=int(options.get(CONF_APP_USAGE_PER_DEVICE, DEFAULT_APP_USAGE_PER_DEVICE)),
			pinned=packages(CONF_APP_USAGE_PINNED),
			excluded=packages(CONF_APP_USAGE_EXCLUDED),
		)


def is_ranked(package: str, excluded: frozenset[str] = frozenset()) -> bool:
	"""Whether an app can be ranked: not excluded, not a launcher or a system screen."""
	return package not in excluded and package not in _SYSTEM_PACKAGES and "launcher" not in package.lower()


def top_packages(totals: dict[str, float] | None, count: int, excluded: frozenset[str] = frozenset()) -> list[str]:
	"""The packages with the most usage, most first, leaving out the barely used and unranked ones."""
	ranked = sorted(
		(
			(package, seconds)
			for package, seconds in (totals or {}).items()
			if seconds >= MIN_RANKED_SECONDS and is_ranked(package, excluded)
		),
		key=lambda item: item[1],
		reverse=True,
	)
	return [package for package, _ in ranked[:max(count, 0)]]


def app_usage_unique_id(child_id: str, package: str, device_id: str | None = None) -> str:
	"""The unique id of a child's app usage sensor, or of the app on one device."""
	if device_id:
		return f"{DOMAIN}_{child_id}_{device_id}_app_usage_{package}"
	return f"{DOMAIN}_{child_id}_app_usage_{package}"


_CHILD_APP = re.compile(rf"^{DOMAIN}_(\d+)_app_usage_(.+)$")
_DEVICE_APP = re.compile(rf"^{DOMAIN}_(\d+)_([A-Za-z0-9-]+)_app_usage_(.+)$")


def parse_app_usage_unique_id(unique_id: str) -> tuple[str, str | None, str] | None:
	"""(child id, device id or None, package) of an app usage sensor's unique id, else None."""
	if match := _CHILD_APP.match(unique_id):
		return match.group(1), None, match.group(2)
	if match := _DEVICE_APP.match(unique_id):
		return match.group(1), match.group(2), match.group(3)
	return None


def app_titles(child_data: dict[str, Any] | None) -> dict[str, str]:
	"""Package name -> title, from the child's app list."""
	return {
		app["packageName"]: app.get("title") or app["packageName"]
		for app in (child_data or {}).get("apps", [])
		if app.get("packageName")
	}
