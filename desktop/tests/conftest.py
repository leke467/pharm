import pytest
from pathlib import Path
from desktop.app.db.database import DatabaseManager
from desktop.app.config.app_config import AppConfig
from desktop.app.sync.api_client import ApiClient

@pytest.fixture
def app_config(tmp_path):
    config = AppConfig(server_url="http://testserver", data_dir=str(tmp_path), log_level="DEBUG")
    return config

@pytest.fixture
def db_manager(app_config):
    manager = DatabaseManager(app_config)
    yield manager
    manager.close()

@pytest.fixture
def api_client(app_config):
    return ApiClient(app_config)

