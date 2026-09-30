import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class RoutingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'routing'

    def ready(self) -> None:
        """
        Runs once when Django starts. We pre-load ("warm") the station cache here
        so the FIRST API request is already fast instead of paying the load cost.
        Wrapped in try/except so a missing data file can't stop the server from
        booting (e.g. before the cache has been built).
        """
        from .services.stations import get_station_store

        try:
            store = get_station_store()
            logger.info("Warmed station cache: %d stations loaded.", len(store))
        except FileNotFoundError as exc:
            logger.warning("Station cache not warmed: %s", exc)
