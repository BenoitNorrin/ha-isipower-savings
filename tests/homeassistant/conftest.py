"""Use actual Home Assistant fixtures in CI; no physical device is needed."""
import pytest



@pytest.fixture(autouse=True)
def _enable_custom_components(enable_custom_integrations):
    yield
