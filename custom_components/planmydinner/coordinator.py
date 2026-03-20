"""DataUpdateCoordinator for Plan My Dinner."""
from __future__ import annotations
import logging
from datetime import date, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, UPDATE_INTERVAL_MINUTES
from .api_client import PlanMyDinnerApiClient

_LOGGER = logging.getLogger(__name__)
# Try both slugs: locally installed add-ons use "local_<slug>", repo add-ons use the plain slug
_ADDON_SLUGS = ["local_planmydinner", "planmydinner"]


async def _fetch_ingress_path(hass: HomeAssistant) -> str | None:
    """Get the add-on ingress URL path via the HA hassio component."""
    # Try the public async_get_addon_info API (HA 2023.3+)
    try:
        from homeassistant.components.hassio import async_get_addon_info
        for slug in _ADDON_SLUGS:
            try:
                info = await async_get_addon_info(hass, slug)
                url = info.get("ingress_url")
                if url:
                    _LOGGER.debug("Got ingress_url via async_get_addon_info for %s: %s", slug, url)
                    return url
                _LOGGER.warning("planmydinner: async_get_addon_info ok for %s but no ingress_url, got keys: %s", slug, list(info.keys()))
            except Exception as e:
                _LOGGER.warning("planmydinner: async_get_addon_info failed for slug %s: %s", slug, e)
    except ImportError as e:
        _LOGGER.warning("planmydinner: async_get_addon_info not available: %s", e)

    # Fallback: search hass.data for a hassio-like handler object
    for key in ["hassio", "homeassistant.components.hassio", "hassio_handler"]:
        obj = hass.data.get(key)
        if obj is not None and hasattr(obj, "get_addon_info"):
            for slug in _ADDON_SLUGS:
                try:
                    info = await obj.get_addon_info(slug)
                    url = info.get("ingress_url")
                    if url:
                        return url
                except Exception as e:
                    _LOGGER.debug("hass.data[%s].get_addon_info(%s) failed: %s", key, slug, e)

    _LOGGER.warning(
        "planmydinner: could not get ingress_url. hass.data keys containing 'hassio': %s",
        [k for k in hass.data if "hassio" in str(k).lower()],
    )
    return None

def _get_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


class PlanMyDinnerCoordinator(DataUpdateCoordinator):
    """Fetches and caches Plan My Dinner data for all sensors."""

    def __init__(
        self,
        hass: HomeAssistant,
        api_client: PlanMyDinnerApiClient,
        profile_id_A: str,
        profile_id_B: str,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=UPDATE_INTERVAL_MINUTES),
        )
        self.api_client = api_client
        self.profile_id_A = profile_id_A
        self.profile_id_B = profile_id_B

    async def _async_update_data(self) -> dict:
        """Fetch all data from the API."""
        today = date.today()
        monday = _get_monday(today)

        results = {}

        # Today's plan (read-only, no generation)
        try:
            results["today"] = await self.api_client.get_plan_for_date(
                self.profile_id_A, self.profile_id_B, today.isoformat()
            )
        except Exception as e:
            _LOGGER.warning("Could not fetch today's plan: %s", e)
            results["today"] = None

        # This week's stored plan
        try:
            results["week"] = await self.api_client.get_weekly_plan_stored(
                self.profile_id_A, self.profile_id_B, monday.isoformat()
            )
        except Exception as e:
            _LOGGER.warning("Could not fetch weekly plan: %s", e)
            results["week"] = None

        # Shopping list
        try:
            results["shopping"] = await self.api_client.get_shopping_list(
                self.profile_id_A, self.profile_id_B, monday.isoformat()
            )
        except Exception as e:
            _LOGGER.warning("Could not fetch shopping list: %s", e)
            results["shopping"] = None

        # Pantry
        try:
            results["pantry"] = await self.api_client.get_pantry_items()
        except Exception as e:
            _LOGGER.warning("Could not fetch pantry: %s", e)
            results["pantry"] = []

        # Ingress path for Lovelace card (via HA Supervisor — no add-on rebuild needed)
        if not hasattr(self, "_ingress_path"):
            self._ingress_path = await _fetch_ingress_path(self.hass)
        results["ingress_path"] = self._ingress_path

        return results
