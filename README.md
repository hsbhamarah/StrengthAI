# StrengthOS AI — Codex starter package

**Requirements baseline:** v0.4–v0.6 of the referenced design conversation, prepared 2026-11-16. The repository now includes an early local implementation; the full P0 MVP is not complete.

## Development startup

Use Python 3.12 and Node.js. In a normal PowerShell window with access to PyPI and npm, run `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run-local.ps1` from this folder. The script creates the local Python environment, installs missing API and React dependencies, builds the UI, initializes SQLite, and starts FastAPI with the built frontend on loopback. On first run it opens `http://127.0.0.1:8000/sign-up` to create the one local coach account. Later runs reuse installed packages and can start offline. Install logs and status are kept under ignored `data/`.

If the app is already running without a coach account, open `http://127.0.0.1:8000/sign-up`. An existing password-only account can run `.\.venv\Scripts\python.exe -m strengthos.setup` to add its email after confirming the current password.

The React frontend now provides coach sign-in, athlete selection and creation, an overview with initial metrics, a searchable training log, and an Excel import flow. For repeated week grids, the mapping screen suggests training tabs and lets the coach edit per-sheet headers, week columns, day/exercise columns, block labels, units, aliases, and individual ambiguous cells. Preview mapped sets and resolve blocking issues before approving a mapping; only the separate commit action writes canonical data. Advanced JSON remains available for row-per-set layouts. Week dates are optional for training import. Select the existing workbook source when uploading a corrected workbook so an approved structural mapping can be reused; cell corrections must be reviewed again.

The health endpoint checks the local Ollama service, and authenticated `/api/v1/ollama/models` lists installed models. AI reviews and recommendations are not implemented yet; a reachable service or installed model does not make them available.

Run available core checks with `python -m unittest discover -s tests -v`. Full API, migration, frontend, and P0 acceptance tests still require dependencies and further implementation.

## Private workspace and recovery

The working database and retained workbooks live in `%LOCALAPPDATA%\StrengthOS` and use SQLCipher encryption. Windows DPAPI protects the daily-use key and coach credentials. The launcher copies the original database and verifies the copy before switching. Review the old files in `data/` and OneDrive history after confirming your new workspace and backup.

Choose **Backup** in the coach workspace and save the encrypted file with a recovery passphrase of at least 16 characters. The backup contains training records, revisions, mappings, and source workbooks. Keep the recovery passphrase separately. To restore on a clean Windows installation, install requirements and run this before launching the app:

```powershell
.\.venv\Scripts\python.exe -m strengthos.storage restore "D:\Backups\workspace.strengthbackup"
.\run-local.ps1
```

Enter the passphrase at the hidden prompt. Restore verifies the database, assigns a new Windows-protected key and refuses to overwrite an existing workspace. Create your coach account on the new device.

## Product in one paragraph

Store optional backend integration credentials using `python -m strengthos.secrets set SERVICE`. Enter the secret at the hidden prompt. Remove it with `python -m strengthos.secrets remove SERVICE`. Credentials are held in Windows Credential Manager and must be reconnected after restore.

Install `requirements-test.txt` for HTTP and migration tests. Before publishing, run `scripts/check-staged.ps1` with Gitleaks available. Dependency update checks are configured for Python and npm.

StrengthOS AI is a local-first coaching workspace for **one coach and multiple athletes**. It imports prescribed and actual training from variable Excel workbooks and authorized Google Sheets, calculates deterministic training metrics, tracks required weekly recovery check-ins through each athlete's Google Sheet, and uses local Ollama to explain evidence and draft recommendations. **The coach approves or rejects recommendations; the application never changes prescriptions automatically.**

## Start here

1. Read `AGENTS.md`, `docs/PRD_SRS.md`, and `docs/DECISIONS.md`.
2. Obtain two representative training workbooks and one example recovery sheet with synthetic or consented data. Do not infer a universal mapping from the examples.
3. Read `docs/BACKLOG.md`; start with M0 and M1.
4. Paste `MASTER_CODEX_PROMPT.md` into a new Codex task with this extracted folder as the workspace.
5. Do not commit real athlete data, OAuth secrets, database files, or local backups.

## Package map

| File | Purpose |
| --- | --- |
| `AGENTS.md` | Engineering rules for Codex |
| `docs/PRD_SRS.md` | Product and system requirements |
| `docs/DECISIONS.md` | Assumptions and open decisions |
| `docs/ADRS.md` | Architecture decisions |
| `db/ERD.md`, `db/schema.sql` | Relational model and executable SQLite starter schema |
| `api/openapi.yaml` | Contract-first API baseline |
| `docs/INGESTION.md` | Variable workbook and source mapping specification |
| `docs/ANALYTICS.md` | Metric definitions, rules, and test vectors |
| `docs/RECOVERY_SHEETS.md` | Google Sheets check-in contract |
| `docs/OLLAMA.md` | Local AI integration and 8 GB benchmark plan |
| `docs/SECURITY_PRIVACY.md` | Security and privacy controls |
| `docs/BACKLOG.md`, `docs/ACCEPTANCE.md` | Ordered work and acceptance gates |
| `docs/SOURCES.md` | Provenance and external documentation |

## Local architecture

React + TypeScript + Vite frontend; FastAPI backend on `127.0.0.1`; SQLite with SQLAlchemy/Alembic; Python ingestion and analytics; one persistent local worker; Ollama on `127.0.0.1:11434`. Production local mode serves the built frontend from FastAPI. Internet is required for Google Sheets sync and initial downloads, but Excel imports, dashboards, metrics, and locally installed Ollama remain usable offline.

## Status and limits

This package consolidates the available v0.4–v0.6 conversation. The referenced thread did **not** contain the original v0.1–v0.3 texts or a real workbook, so those earlier versions cannot be verified line by line. `docs/DECISIONS.md` records this gap. Model choices and latency budgets are candidates until measured on the actual Windows 8 GB laptop. API and SQL are a coherent starting contract that implementation can refine with explicit migrations and contract changes.
