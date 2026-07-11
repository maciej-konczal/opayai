import pytest


@pytest.fixture(autouse=True)
def _isolated_authstore(tmp_path, monkeypatch):
    """Give every test its own on-disk authorization store (cross-process auth)."""
    monkeypatch.setenv("OPAYAI_AUTH_STORE", str(tmp_path / "auth"))
