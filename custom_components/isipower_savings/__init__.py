"""Config-entry lifecycle for Isipower Savings."""
from homeassistant.const import Platform
from homeassistant.exceptions import ConfigEntryNotReady

from .config import normalize
from .coordinator import SavingsCoordinator

PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(hass, entry):
    config = normalize({**entry.data, **entry.options})
    coordinator = SavingsCoordinator(hass, config)
    try:
        await coordinator.async_load()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ConfigEntryNotReady("Historique local à vérifier ; ne pas supprimer les fichiers") from exc
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_options_updated))
    await coordinator.async_start()
    return True


async def _options_updated(hass, entry):
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass, entry):
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.async_stop()
        return True
    return False
