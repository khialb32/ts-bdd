import pytest

from ambilight import device


@pytest.fixture(autouse=True)
def no_flush_wait(monkeypatch):
    monkeypatch.setattr(device, "FLUSH_BEFORE_DISCONNECT", 0)
