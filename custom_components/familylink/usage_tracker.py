"""Apps whose usage grew since the last refresh, from Google's daily totals.

Google has no session times, only a daily total per app and device, and a
device uploads its usage in batches (about every 5 minutes for a phone in use,
15 to 20 for a tablet). So this reports what was measured, not what the child
was doing: an app whose total grew between two refreshes, by how much, and when
Google received it (the use itself happened before that). The event entity
(event.py) fires one event per app and device that grew.

The first refresh of a day, or after a restart, only sets the baseline: what
grew while Home Assistant was not looking is not known.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# Growth below this many seconds is rounding between two answers, not use
MIN_GROWTH_SECONDS = 1


class UsageGrowthTracker:
	"""Remembers each child's last totals to see which apps grew since."""

	def __init__(self) -> None:
		self._seen: dict[str, tuple[Any, dict[tuple[str, str], float]]] = {}  # child -> (day, seconds per (package, device))

	def update(self, child_id: str, screen_time: dict[str, Any] | None, now: datetime) -> list[dict[str, Any]]:
		"""Record this refresh and return what grew since the last one, the most first."""
		if not screen_time:
			return []
		day = screen_time.get("date")
		seen_day, seen = self._seen.get(child_id, (None, {}))
		# When Google received the usage; never later than now
		received = min(now, _received_at(screen_time.get("data_refreshed_ms")) or now)
		devices = screen_time.get("device_names") or {}

		current: dict[tuple[str, str], float] = {}
		grew: list[dict[str, Any]] = []
		for item in screen_time.get("app_device_usage") or []:
			key = (item.get("package"), item.get("device_id"))
			current[key] = item.get("seconds") or 0
			delta = current[key] - seen.get(key, 0)
			if seen_day == day and delta > MIN_GROWTH_SECONDS:
				grew.append({
					"package": key[0],
					"device": devices.get(key[1], key[1]),
					"grew_minutes": round(delta / 60, 1),
					"today_minutes": round(current[key] / 60, 1),
					"reported_at": received.isoformat(),
				})
		self._seen[child_id] = (day, current)
		return sorted(grew, key=lambda event: event["grew_minutes"], reverse=True)

	def retain(self, child_ids: set[str]) -> None:
		"""Forget children that are no longer in the family."""
		for child_id in [c for c in self._seen if c not in child_ids]:
			del self._seen[child_id]


def _received_at(millis: Any) -> datetime | None:
	"""Google's "usage received" time (epoch milliseconds), None when absent or unreadable."""
	try:
		return datetime.fromtimestamp(int(millis) / 1000, timezone.utc)
	except (TypeError, ValueError, OverflowError, OSError):
		return None
