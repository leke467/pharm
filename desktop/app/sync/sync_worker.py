import threading
from PySide6.QtCore import QThread, Signal
from desktop.app.db.models import Organization, Branch
from desktop.app.sync.sync_engine import SyncEngine
from desktop.app.services.licensing_service import LicensingService
from desktop.app.services.backup_service import BackupService


class SyncWorker(QThread):
    sync_status_changed = Signal(bool)
    sync_error = Signal(str)
    events_pending = Signal(int)
    sync_completed = Signal(dict)
    subscription_updated = Signal(dict)
    cloud_backup_synced = Signal(dict)

    def __init__(self, api_client, db_manager, config, session_provider=None):
        super().__init__()
        self.api_client = api_client
        self.db_manager = db_manager
        self.config = config
        self.session_provider = session_provider
        self.engine = SyncEngine(api_client, db_manager)
        self.licensing_service = LicensingService(db_manager)
        self.backup_service = BackupService(db_manager, config)
        self._is_running = False
        self._stop_event = threading.Event()

    def _resolve_branch_context(self, session) -> tuple[str, str, str, str]:
        org_code = "MEDCARE"
        org_name = getattr(session, "organization_name", "") or "MedCare Pharmacy"
        branch_code = "HQ"
        branch_name = getattr(session, "branch_name", "") or "Main Branch"
        try:
            with self.db_manager.get_session() as db:
                if session and session.organization_id:
                    org = db.query(Organization).filter_by(id=session.organization_id).first()
                    if org:
                        org_code = org.code or org_code
                        org_name = org.name or org_name
                if session and session.branch_id:
                    br = db.query(Branch).filter_by(id=session.branch_id).first()
                    if br:
                        branch_code = br.code or branch_code
                        branch_name = br.name or branch_name
        except Exception:
            pass
        return org_code, org_name, branch_code, branch_name

    def run(self):
        self._is_running = True
        self._stop_event.clear()
        while self._is_running and not self._stop_event.is_set():
            try:
                pending = self.engine.get_pending_count()
                if not self._is_running:
                    break
                self.events_pending.emit(pending)

                is_online = self.api_client.is_server_available()
                if not self._is_running:
                    break
                self.sync_status_changed.emit(is_online)

                session = self.session_provider() if callable(self.session_provider) else None
                if is_online and self._is_running:
                    # 1. Confirm subscription days left from Django server & save locally
                    org_id = session.organization_id if session else None
                    lic_state = self.licensing_service.sync_subscription_from_server(
                        self.api_client,
                        organization_id=org_id,
                    )
                    if lic_state and self._is_running:
                        self.subscription_updated.emit(lic_state)

                if (
                    self._is_running
                    and is_online
                    and session
                    and session.organization_id
                    and session.branch_id
                    and session.device_id
                ):
                    # 2. Event outbox / inbox sync (when JWT token is active)
                    if getattr(session, "access_token", None):
                        try:
                            result = self.engine.sync_once(
                                organization_id=session.organization_id,
                                branch_id=session.branch_id,
                                device_id=session.device_id,
                            )
                            if self._is_running:
                                self.sync_completed.emit(result)
                                self.events_pending.emit(self.engine.get_pending_count(session.branch_id))
                        except Exception:
                            pass

                    # 3. Automatic Per-Branch Cloud Backup on Sync (Max 4 backups per branch in FILO order)
                    if self._is_running:
                        try:
                            org_code, org_name, branch_code, branch_name = self._resolve_branch_context(session)
                            bck_res = self.backup_service.upload_branch_backup_to_cloud(
                                api_client=self.api_client,
                                org_code=org_code,
                                org_name=org_name,
                                branch_id=session.branch_id,
                                branch_code=branch_code,
                                branch_name=branch_name,
                                device_code=getattr(session, "device_code", "POS01") or "POS01",
                                note="Auto-Sync Cloud Backup",
                                force_new_slot=False,
                            )
                            if bck_res and self._is_running:
                                self.cloud_backup_synced.emit(bck_res)
                        except Exception:
                            pass
            except Exception as exc:
                if self._is_running:
                    self.sync_error.emit(str(exc))

            if self._stop_event.wait(timeout=max(1, self.config.sync_interval)):
                break

    def request_stop(self):
        self._is_running = False
        self._stop_event.set()

    def stop(self, timeout_ms: int = 200):
        self.request_stop()
        if self.isRunning():
            if not self.wait(timeout_ms):
                self.terminate()
                self.wait(50)

