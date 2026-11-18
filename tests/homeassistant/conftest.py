"""Use actual Home Assistant fixtures in CI; no physical device is needed."""
import pytest
from unittest.mock import AsyncMock, patch



@pytest.fixture(autouse=True)
def _enable_custom_components(enable_custom_integrations):
    yield


@pytest.fixture(autouse=True)
def _recorder_dependency():
    # These tests exercise the flow manager and our adapter, not HA's database
    # bootstrap. Recorder writes are intercepted separately in adapter tests.
    with patch("homeassistant.components.recorder.async_setup", new=AsyncMock(return_value=True)):
        yield
