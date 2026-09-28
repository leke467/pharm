# Pharmacy Management System: Deployment & Production Guide

This guide details how to build, containerize, and deploy the Pharmacy Management System across server and desktop environments.

---

## 1. Central Server Deployment (PostgreSQL + Django REST Framework)

### Prerequisites
- Docker & Docker Compose OR Python 3.12+ and PostgreSQL 16+
- SSL Certificate (Let's Encrypt / Cloudflare)
- Reverse proxy (Nginx or Caddy)

### Option A: Docker Deployment (Recommended)
1. Clone the repository and configure your environment:
   ```bash
   cp .env.example .env
   # Edit .env with secure production credentials (SECRET_KEY, DATABASE_URL)
   ```
2. Build and launch containers:
   ```bash
   docker-compose up -d --build
   ```
3. Run migrations and collect static files:
   ```bash
   docker-compose exec server python manage.py migrate
   docker-compose exec server python manage.py collectstatic --noinput
   ```
4. Create default superuser or tenant:
   ```bash
   docker-compose exec server python manage.py createsuperuser
   ```

### Option B: Bare-Metal / Systemd Deployment
1. Set up virtual environment and install dependencies:
   ```bash
   cd server
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
2. Configure Gunicorn service unit (`/etc/systemd/system/pharmacy.service`):
   ```ini
   [Unit]
   Description=Pharmacy Management Server
   After=network.target

   [Service]
   User=pharmacy
   WorkingDirectory=/opt/pharmacy/server
   ExecStart=/opt/pharmacy/server/venv/bin/gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 4
   Restart=always

   [Install]
   WantedBy=multi-user.target
   ```
3. Configure periodic maintenance cron jobs:
   ```cron
   # Daily SyncDelivery pruning (90-day retention)
   0 2 * * * /opt/pharmacy/server/venv/bin/python /opt/pharmacy/server/manage.py cleanup_sync_deliveries
   # Weekly Inventory Ledger Reconciliation
   0 3 * * 0 /opt/pharmacy/server/venv/bin/python /opt/pharmacy/server/manage.py reconcile_inventory
   # Monthly Audit Event Archival
   0 4 1 * * /opt/pharmacy/server/venv/bin/python /opt/pharmacy/server/manage.py archive_audit_events
   ```

---

## 2. Desktop Application Packaging (Windows)

### Prerequisites
- Python 3.12 64-bit on Windows
- PyInstaller: `pip install pyinstaller`
- Inno Setup 6 (for creating the Windows `.exe` setup installer)

### Step 1: Build the Executable
Run the automated build script:
```powershell
python desktop/packaging/build.py
```
This generates a self-contained application folder in `desktop/packaging/dist/PharmacyManagement/` containing:
- `PharmacyManagement.exe`
- Embedded SQLite with FTS5 search
- PySide6 Qt GUI runtime
- Stylesheets, assets, and database migration runner

### Step 2: Build the Windows Installer
Compile `desktop/packaging/inno_setup.iss` using Inno Setup Compiler (`ISCC.exe`):
```powershell
iscc.exe desktop/packaging/inno_setup.iss
```
The final standalone installer `PharmacyManagementSetup_v1.0.0.exe` will be generated in `installer_output/`.

---

## 3. Disaster Recovery & Backups

- **Server**: Daily PostgreSQL dumps (`pg_dump`) and continuous WAL archiving for point-in-time recovery (PITR).
- **Desktop**: Automatic zero-lock SQLite online backups to `%LOCALAPPDATA%/PharmacyManagement/backups` with 30-day retention pruning.
