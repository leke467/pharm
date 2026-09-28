# Pharmacy Management System

A commercial, production-ready pharmacy management system for pharmacies operating one or more branches. Built with an **offline-first** architecture, the system stores data locally at each branch and synchronizes with a central cloud backend when Internet is available.

## Architecture

```
Branch Device (Desktop App)          Central Server (Cloud)
┌────────────────────────┐          ┌────────────────────────┐
│  PySide6 UI            │          │  Django REST Framework  │
│  ├── Services          │   HTTPS  │  ├── API Endpoints      │
│  ├── Domain Logic      │◄────────►│  ├── Sync Engine        │
│  ├── Repositories      │          │  ├── Auth (JWT)         │
│  └── SQLite (WAL)      │          │  └── PostgreSQL         │
└────────────────────────┘          └────────────────────────┘
```

- **Desktop**: Python + PySide6 + SQLAlchemy + SQLite
- **Server**: Python + Django + Django REST Framework + PostgreSQL
- **Communication**: REST API over HTTPS with JWT authentication
- **Sync**: Event-based synchronization (never database-file copying)
- **Multi-tenant**: Row-level organization isolation

## Key Features

- Multi-organization, multi-branch, multi-device
- Offline-first — all operations work without Internet
- Product + Batch separation with FEFO/FIFO batch selection
- Immutable inventory movement ledger
- Role-based access control with granular permissions
- Stock count with approval workflow
- Comprehensive audit trail
- Event-based synchronization
- Receipt printing (thermal printers)
- Subscription/licensing system

## Project Structure

```
pharm/
├── server/              # Django REST API (central server)
│   ├── config/          # Django settings, URLs, WSGI
│   ├── apps/            # Django applications
│   │   ├── core/        # Base models, permissions, middleware
│   │   ├── organizations/
│   │   ├── branches/
│   │   ├── users/
│   │   ├── sync/
│   │   ├── audit/
│   │   └── api/         # API routing and health check
│   └── tests/
├── desktop/             # PySide6 desktop application
│   ├── app/
│   │   ├── config/      # App configuration
│   │   ├── db/          # SQLAlchemy models, migrations
│   │   ├── repositories/
│   │   ├── services/
│   │   ├── domain/      # Business rules, enums, exceptions
│   │   ├── auth/        # Authentication (online + offline)
│   │   ├── sync/        # API client, sync worker
│   │   ├── printing/    # Receipt printing
│   │   ├── ui/          # PySide6 widgets and screens
│   │   └── utils/       # Logging, date/UUID helpers
│   └── tests/
├── shared/              # Shared enums and constants
├── .env.example         # Environment variable template
└── .gitignore
```

## Development Setup

### Prerequisites

- Python 3.11+
- PostgreSQL 15+ (for the central server)
- Git

### 1. Clone the Repository

```bash
git clone <repo-url>
cd pharm
```

### 2. Create Environment File

```bash
cp .env.example .env
# Edit .env with your local settings
```

### 3. Set Up the Central Server

```bash
cd server
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux

pip install -r requirements.txt

# Create PostgreSQL database
# psql -U postgres -c "CREATE DATABASE pharmacy_db;"
# psql -U postgres -c "CREATE USER pharmacy_user WITH PASSWORD 'pharmacy_password';"
# psql -U postgres -c "GRANT ALL PRIVILEGES ON DATABASE pharmacy_db TO pharmacy_user;"

python manage.py migrate
python manage.py runserver
```

The server will be available at `http://localhost:8000`.

### 4. Set Up the Desktop Application

```bash
cd desktop
python -m venv venv
venv\Scripts\activate

pip install -r requirements.txt

python -m app.main
```

The desktop app creates its SQLite database automatically in the OS app-data directory.

### 5. Run Tests

```bash
# Server tests
cd server
pip install pytest pytest-django
pytest

# Desktop tests
cd desktop
pip install pytest
pytest
```

## Environment Variables

See [`.env.example`](.env.example) for all available configuration options.

### Required for Server

| Variable | Description |
|---|---|
| `DJANGO_SECRET_KEY` | Django secret key |
| `DATABASE_URL` | PostgreSQL connection URL |

### Required for Desktop

| Variable | Description |
|---|---|
| `PHARMACY_SERVER_URL` | Central server URL |

## Architecture Documentation

- [Architecture Plan](docs/architecture_plan.md) — Complete system architecture
- [Phase 1 Implementation Plan](phase1_implementation_plan.md) — Current phase scope

## License

Proprietary — All rights reserved.
