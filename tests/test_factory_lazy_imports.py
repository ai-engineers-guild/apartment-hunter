import sys
from importlib import reload

from apartment_hunter.storage import factory


def test_factory_lazy_imports_storage(mocker) -> None:
    # Ensure connectors are not loaded
    if "apartment_hunter.storage.connectors.postgres" in sys.modules:
        del sys.modules["apartment_hunter.storage.connectors.postgres"]

    # Reload factory to ensure clean state
    reload(factory)

    # Mock settings to return sqlite (default)
    mock_settings = mocker.MagicMock()
    mock_settings.storage_backend = "sqlite"
    mock_settings.db_path = ":memory:"
    mocker.patch("apartment_hunter.storage.factory.get_settings", return_value=mock_settings)

    # Calling get_storage with sqlite should not trigger postgres import
    store = factory.get_storage()
    assert store is not None
    assert "apartment_hunter.storage.connectors.postgres" not in sys.modules
