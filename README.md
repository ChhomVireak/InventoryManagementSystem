# Inventory Management System (SETEC SV34 – ADV Python)

Django project modelled on school_management (app_* apps, AdminLTE 3), implementing the IMS requirements PDF.

## Run (zero setup, SQLite)
    pip install -r requirements.txt
    USE_SQLITE=1 python manage.py migrate
    USE_SQLITE=1 python manage.py seed_demo
    USE_SQLITE=1 python manage.py runserver
## Run (PostgreSQL)
Copy `.env.example` to `.env`, set DB_*, then `python manage.py migrate && python manage.py seed_demo`, or `docker compose up --build`.

## Demo logins (password `Ims@12345`)
admin, manager, warehouse, purchasing, sales, accountant

## Modules
product, warehouse, supplier, customer, stock (in/out/adjust/transfer/count, barcode scan), purchase, sales, returns, notification, report (8 reports + CSV + KPI), REST API (`/api/`, JWT via `/api/token/`).

## Notes / deviations from the PDF
- Extra permissions: `po.approve`, `stock.adjust.approve` (also approves returns and counts).
- Added StockAdjustment model for FR-08 pending approvals.
- Sales tax rate 10% (settings); `reserved_quantity` kept but not auto-populated (SALES_ORDER has no warehouse in ERD).
- Tested on SQLite (`USE_SQLITE=1 python manage.py test`); PostgreSQL configured but untested.
- Alerts: `python manage.py check_alerts` (schedule daily). Backups: `scripts/backup.sh`.
