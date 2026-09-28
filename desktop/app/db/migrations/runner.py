import importlib
import pkgutil
import shutil
from datetime import datetime, timezone
from desktop.app.db.models import SchemaVersion
import desktop.app.db.migrations.versions as versions

class MigrationRunner:
    def __init__(self, db_manager, config):
        self.db_manager = db_manager
        self.config = config

    def get_current_version(self, session):
        try:
            version = session.query(SchemaVersion).order_by(SchemaVersion.version.desc()).first()
            return version.version if version else 0
        except Exception:
            return 0

    def backup_db(self):
        if self.config.db_path.exists():
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_path = self.config.backup_dir / f"pharmacy_pre_migration_{timestamp}.db"
            shutil.copy2(self.config.db_path, backup_path)

    def run_pending(self):
        with self.db_manager.get_session() as session:
            current = self.get_current_version(session)
            
            # Find all migration modules (works in both standard Python and PyInstaller frozen builds)
            migration_modules = set()
            for _, name, _ in pkgutil.iter_modules(versions.__path__):
                if name.startswith(tuple("0123456789")):
                    migration_modules.add(name)
            for path_dir in getattr(versions, "__path__", []):
                try:
                    import os
                    for fname in os.listdir(path_dir):
                        if fname.endswith(".py") and fname[0].isdigit():
                            migration_modules.add(fname[:-3])
                except Exception:
                    pass

            migration_modules = sorted(migration_modules)
            
            for mod_name in migration_modules:
                version_num = int(mod_name.split('_')[0])
                if version_num > current:
                    self.backup_db()
                    mod = importlib.import_module(f"desktop.app.db.migrations.versions.{mod_name}")
                    if hasattr(mod, 'upgrade'):
                        mod.upgrade(session)
                        # Add schema version record if the migration script didn't
                        if not session.query(SchemaVersion).filter_by(version=version_num).first():
                            sv = SchemaVersion(version=version_num, description=mod_name)
                            session.add(sv)
                        session.commit()

