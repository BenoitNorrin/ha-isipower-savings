"""Adapter tests using real HA State objects, with recorder writes intercepted."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from custom_components.isipower_savings.config import normalize
from custom_components.isipower_savings.coordinator import SavingsCoordinator


def config(**extra):
    return normalize({"consumption_sensor": "sensor.home_power", "grid_sensor": "sensor.grid_power",
        "source_timestamp": "sensor.report_at", "base_rate": .25, **extra})


def states(hass, when, home=1000, grid=400):
    hass.states.async_set("sensor.home_power", str(home), {"unit_of_measurement": "W"})
    hass.states.async_set("sensor.grid_power", str(grid), {"unit_of_measurement": "W"})
    hass.states.async_set("sensor.report_at", when.isoformat())


async def test_partial_day_and_recorded_prices(hass):
    now = datetime(2026, 1, 10, 12, tzinfo=timezone.utc)
    cfg = config()
    c = SavingsCoordinator(hass, cfg)
    c.now = lambda: now
    writes = []
    with patch("custom_components.isipower_savings.coordinator.async_add_external_statistics",
               side_effect=lambda *args: writes.append(args)):
        await c.async_load()
        states(hass, now)
        await c.async_capture()
        now += timedelta(minutes=5)
        states(hass, now)
        await c.async_capture()
        result = c.journal.engine.summary("jour", now)
        assert result["benefit"] > 0
        assert result["measured_hours"] == .08
        assert {item[1]["statistic_id"] for item in writes} == {
            "isipower_savings:benefit", "isipower_savings:savings", "isipower_savings:revenue",
            "isipower_savings:with_installation", "isipower_savings:without_installation"}
        other = SavingsCoordinator(hass, cfg)
        other.now = lambda: now
        await other.async_load()
        assert other.journal.engine.summary("jour", now) == result


async def test_additional_load_is_optional_and_is_not_added_to_grid(hass):
    now = datetime(2026, 1, 10, 12, tzinfo=timezone.utc)
    c = SavingsCoordinator(hass, config(additional_consumption=["sensor.workshop_power"]))
    states(hass, now, home=1000, grid=5000)
    hass.states.async_set("sensor.workshop_power", "4", {"unit_of_measurement": "kW"})
    reading = c.reading(now)
    assert reading["consumption_w"] == 5000
    assert reading["grid_w"] == 5000


async def test_unavailable_additional_load_is_not_assumed_zero(hass):
    now = datetime(2026, 1, 10, 12, tzinfo=timezone.utc)
    c = SavingsCoordinator(hass, config(additional_consumption=["sensor.workshop_power"]))
    states(hass, now)
    hass.states.async_set("sensor.workshop_power", "unavailable")
    assert c.reading(now)["error"] == "source_unavailable"


async def test_separate_export_and_opposite_grid_sign(hass):
    now = datetime(2026, 1, 10, 12, tzinfo=timezone.utc)
    c = SavingsCoordinator(hass, config(invert_grid=True, export_sensor="sensor.export_power"))
    states(hass, now, grid=-400)
    hass.states.async_set("sensor.export_power", "200", {"unit_of_measurement": "W"})
    result = c.reading(now)
    assert result["grid_w"] == 400
    assert result["export_w"] == 200


async def test_stale_report_does_not_create_fake_ongoing_consumption(hass):
    now = datetime(2026, 1, 10, 12, tzinfo=timezone.utc)
    c = SavingsCoordinator(hass, config())
    states(hass, now-timedelta(hours=1))
    assert c.reading(now)["error"] == "source_stale"
