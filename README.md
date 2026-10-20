# Finsleuth
React + TypeScript frontend, FastAPI backend, MongoDB, and bundled trained models. Python 3.13 (64-bit standard build) is supported. No Docker is needed.

## Run locally
Install Python 3.13, Node.js with npm, and MongoDB Community Server, or configure a MongoDB Atlas connection. MongoDB must be running before setup.

From the extracted **Finsleuth** folder:

```powershell
python manage.py setup
python manage.py serve
```

Open **http://localhost:8000**. One server serves both the compiled frontend and backend. Do not open index.html directly or use an old frontend server on port 5173.

If using Atlas or an existing database, copy `backend/.env.example` to `backend/.env` and set `MONGODB_URI` and `MONGODB_DATABASE` before setup. Reuse your earlier database settings to retain pending registrations and investigations.

## Administrator login and recovery
The administrator email is **admin@finsleuth.local**. Setup generates a random password in **LOCAL_ADMIN.txt** on your computer and prints its location. Open that file to sign in. No universal password is shipped. Setup creates the account if absent. If you already have an administrator with a different password, use this explicit trusted-host recovery command:

```powershell
python manage.py reset-admin
```

This resets only the active `admin@finsleuth.local` account to the locally generated password and revokes that account's sessions. Other users and records are preserved. Change the password under My profile after signing in. Keep LOCAL_ADMIN.txt private and out of source control.

To approve a registration: sign in as the **operational administrator**, open **Users & approvals**, choose **Review access**, select **Active**, enter a rationale, and save. The applicant can now sign in. Demo administrator approvals affect only the isolated demo.

## Data flow and testing your records
The administrator uploads data. Analysts and compliance managers access the same operational workspace; managers assign/review cases rather than distribute separate dataset copies.

1. Admin → Datasets & quality → upload CSV or ZIP containing one CSV.
2. Enter source/licence, validate, inspect the quality report, then Confirm import.
3. Click Score records to apply the deployed model in restartable batches. Keep this page open until complete; clicking again safely resumes remaining records.
4. Approved analyst → Transaction alerts → search for your transaction ID → inspect prediction → Score & explain → create case, add notes and submit.
5. Approved compliance manager → Review & assignments → review, return, assign, escalate or close with rationale.

Required columns: `transaction_id`, `transaction_date`, `transaction_amount`, `is_fraud` (0 or 1). Optional `transaction_time` accepts HH:MM or HH:MM:SS. The model uses amount, hour, weekday, transaction_type, transaction_direction, channel, merchant_category, and account_type. Supply those model fields for meaningful predictions; absent categorical values become Unknown.

For actual network/trace analysis, also supply `sender_id` and `recipient_id`. Both are required on every row when supplied. Source IDs must be unique across the workspace. The supplied banking archive has no sender/recipient pairs. Its graph cannot establish account-to-account transfers. Demo mode provides a separately labelled fictional graph that is never used for training.

Setup registers five bundled models (four candidates and their supplied hybrid) and the latest 2,000 unchanged archive records. It does not create fake operational cases. The full 550,000-row archive was used for training/evaluation. Demo workspaces include illustrative cases and a connected-account scenario. Demo accounts cannot access operational registrations.

## Deploy without Docker
Use a host that supports Python 3.13 and persistent storage, with MongoDB or Atlas. Run setup during provisioning, then use:

```bash
python manage.py serve --host 0.0.0.0 --port 8000
```

Terminate HTTPS at your hosting service and set `COOKIE_SECURE=true`. Set `MONGODB_REQUIRE_TRANSACTIONS=true` with Atlas/replica sets. Keep `backend/.env`, dataset uploads, model artifacts and LOCAL_ADMIN.txt outside public static directories. Persist `artifacts/runtime` and MongoDB storage across deploys. The frontend is served from `frontend/dist` only. No external email provider is configured automatically; password-recovery email requires SMTP environment configuration.

## Project layout
- `frontend/src/pages`: entry, investigation, cases, administration and profile pages.
- `frontend/src/components`: shared UI, brand and landing illustration.
- `backend/app`: authentication, database repository, operations, case workflow and dataset/model services.
- `backend/ml`: ZIP loading, training, validation and inference.
- `backend/tests`, `frontend/e2e`: workflow and browser checks.
- `artifacts/dataset`: fitted models and measured evaluation reports.
- `data/archive.zip`: unchanged supplied training archive, read with Python zipfile.
- `manage.py`: setup, serve and administrator recovery commands.

## Developer checks
From backend, install requirements-test.txt and run `python -m pytest -q`. From frontend, run `npm test` and `npm run build`. Test code uses an explicitly gated Mongo substitute; it must not be used for deployment. Model performance and monitoring are restricted to administrators; managers cannot access their APIs or frontend routes.

Browser checks use `python scripts/browser_qa.py` after installing Playwright Chromium.

## Current verification and limitations
Read `RELEASE_REPORT.md` for the checks actually executed and remaining gaps, and `MODEL_EVALUATION.md` for measured metrics. No candidate has demonstrated both 85% accuracy and 85% fraud recall on the supplied banking archive. Do not interpret high overall accuracy as strong fraud detection.

## Administrator-controlled dataset access
- Each dataset has an explicit access list of active Bank Analysts and Compliance Managers, chosen by the administrator at upload (`access_user_ids`) and editable later with `PUT /api/v1/admin/datasets/{id}/access` (`GET` reads it; `GET /api/v1/admin/access-users` lists eligible people).
- Enforced in the backend for transactions, predictions, accounts, graph/trace, alerts, cases (detail, evidence, attachments, reports, PDF), compliance CSV, quality report and overview. Users without access receive empty results or 404.
- A case is visible only if every transaction attached to it belongs to a dataset the user can access. Revoking access hides it immediately; re-granting restores it.
- Grants, changes and revocations are recorded in the audit log (`dataset.access_granted`, `dataset.access_changed`, `dataset.access_revoked`) with previous/current/added/removed users.
- Existing datasets start with no grants after upgrade; the administrator must select users (Datasets → Access). Demo workspaces pre-grant their demo personas.
