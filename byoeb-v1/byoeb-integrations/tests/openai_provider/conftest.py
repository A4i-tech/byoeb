import urllib.request
import pytest

MOCK_SERVER = "http://localhost:8000"


@pytest.fixture(scope="session")
def mock_base_url():
    try:
        urllib.request.urlopen(f"{MOCK_SERVER}/health", timeout=2)
    except OSError:
        pytest.skip(f"The mock model server does not answer at {MOCK_SERVER}/health. Start it from C:/A4I/mock-services/model-server.")
    return f"{MOCK_SERVER}/v1"
