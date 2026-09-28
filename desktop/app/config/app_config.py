import os
from pathlib import Path
from dotenv import load_dotenv
from .constants import DEFAULT_HTTP_TIMEOUT, DEFAULT_SYNC_INTERVAL

class AppConfig:
    def __init__(self, server_url=None, data_dir=None, log_level=None):
        load_dotenv()
        if data_dir:
            self.data_dir = Path(data_dir)
        else:
            custom_dir = os.getenv("PHARMACY_DATA_DIR")
            if custom_dir:
                self.data_dir = Path(custom_dir)
            elif os.name == 'nt':
                local_app_data = os.getenv("LOCALAPPDATA")
                self.data_dir = Path(local_app_data) / "PharmacyManagement"
            else:
                self.data_dir = Path.home() / ".pharmacymanagement"

        self.data_dir.mkdir(parents=True, exist_ok=True)
        data_env_file = self.data_dir / ".env"
        if data_env_file.exists():
            load_dotenv(dotenv_path=data_env_file, override=True)

        self.server_url = server_url or os.getenv("PHARMACY_SERVER_URL", "http://127.0.0.1:8001")
        self.device_code = os.getenv("PHARMACY_DEVICE_CODE", "POS01")
        self.db_path = self.data_dir / 'pharmacy.db'
        self.backup_dir = self.data_dir / 'backups'
        self.log_dir = self.data_dir / 'logs'
        self.log_level = log_level or os.getenv("PHARMACY_LOG_LEVEL", "INFO")
        self.sync_interval = int(os.getenv("PHARMACY_SYNC_INTERVAL_SECONDS", DEFAULT_SYNC_INTERVAL))
        self.http_timeout = int(os.getenv("PHARMACY_HTTP_TIMEOUT_SECONDS", DEFAULT_HTTP_TIMEOUT))

        self.backup_dir.mkdir(parents=True, exist_ok=True)

