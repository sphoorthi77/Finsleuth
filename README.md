# Finsleuth — AI/ML-Powered Financial Fraud Detection and Investigation

Finsleuth is an AI/ML-powered financial fraud detection and investigation platform designed to help financial institutions identify potentially suspicious transactions, understand model predictions, investigate account relationships, and manage cases through a structured compliance workflow.

The platform combines supervised machine learning, transaction-risk scoring, prediction explainability, account-network analysis, money-flow investigation, and role-based case management.

Finsleuth is designed to assist human investigators. A high-risk prediction indicates that a transaction may require further examination; it is not proof of fraud.

## Table of Contents

1. Problem Statement
2. Proposed Solution
3. How AI/ML Is Used
4. Machine Learning Pipeline
5. Algorithms and Models
6. Feature Engineering
7. System Architecture
8. Technology Stack
9. Dataset and Data Requirements
10. User Roles and Features
11. Local Installation and Setup
12. Administrator Login
13. How to Use Finsleuth
14. Dataset Import and Transaction Scoring
15. Investigation and Case Management
16. Account Network and Money-Flow Analysis
17. Model Evaluation and Fraud Recall
18. Database and Access Control
19. Security and Responsible Use
20. Testing
21. Project Structure
22. Limitations
23. Future Enhancements

---

## 1. Problem Statement

Financial institutions process large volumes of transactions through payment channels such as UPI, IMPS, NEFT, RTGS, cards, and online banking. Identifying fraudulent activity among legitimate transactions is challenging because suspicious transactions can resemble ordinary financial activity.

Fraud may involve unusual transaction amounts, unexpected timing, abnormal transaction frequency, or transfers between multiple accounts. Examining individual transactions in isolation may not reveal the complete pattern.

Traditional rule-based systems rely on predefined conditions. Although useful, these rules may miss unfamiliar patterns and generate excessive false-positive alerts, increasing the workload of investigators.

Another challenge is explainability. A risk score alone does not tell an investigator why a transaction was flagged, which factors influenced the prediction, or what evidence should be reviewed next.

Financial institutions therefore need a system that can:

- Learn patterns from historical fraud-labelled transactions.
- Identify transactions that resemble previously labelled fraudulent activity.
- Prioritise records for investigation.
- Explain model predictions using available transaction features.
- Explore connected accounts when reliable relationship data exists.
- Reconstruct recorded transaction paths.
- Organise evidence and findings into investigation cases.
- Support compliance review, decisions, and escalation.
- Maintain traceable records of important actions.

## 2. Proposed Solution

Finsleuth connects machine-learning predictions with investigation and compliance workflows.

Its central workflow is:

**Detect → Explain → Investigate → Trace → Review**

### Detect

A trained classification model analyses eligible transaction features and estimates fraud risk.

### Explain

The application presents the prediction and relevant contributing features, helping analysts understand why a transaction may require attention.

### Investigate

Analysts inspect transaction details, examine available account history, record observations, and create cases with supporting evidence.

### Trace

When sender and recipient information is available, investigators can explore account relationships and examine recorded transaction paths.

### Review

Compliance managers examine submitted cases, request additional evidence, assign work, and document review decisions.

System administrators manage users, datasets, model versions, and system health.

The goal is to turn a model prediction into a structured, evidence-based investigation rather than relying on a classification result alone.

## 3. How AI/ML Is Used

AI/ML is the analytical core of Finsleuth.

### Supervised fraud classification

The model learns statistical relationships between transaction features and historical fraud labels.

- `is_fraud = 1`: the transaction is labelled fraudulent in the dataset.
- `is_fraud = 0`: the transaction is labelled legitimate in the dataset.

The trained classifier estimates the likelihood of the positive class based on the input features.

This prediction reflects learned patterns in the training data. It does not independently establish whether a real transaction is fraudulent.

### Transaction-risk scoring

The application loads the selected model and its associated preprocessing pipeline. Transaction inputs are transformed into the expected feature format before inference.

The resulting score can help prioritise transactions for review using an appropriately evaluated decision threshold.

### Explainable predictions

Feature explanations help investigators understand which inputs contributed to a prediction.

Depending on the fitted model and implemented explanation method, relevant features may include transaction amount, timing, payment channel, transaction type, and other supported model inputs.

Explanations describe model behaviour; they are not proof of fraudulent intent.

### Imbalanced classification

Fraud-labelled records are often a small minority of the dataset. A model can achieve high overall accuracy while missing many fraudulent transactions.

Finsleuth therefore considers fraud precision, recall, F1-score, precision-recall AUC, ROC-AUC, and false-positive burden.

The decision threshold must balance missed fraud-labelled records against the number of legitimate transactions incorrectly flagged.

### Transaction-history analysis

Where reliable historical records exist, additional features can represent transaction frequency, recency, and deviations from previous activity.

These features must use only information available before the transaction being scored. Future transactions and future labels must not leak into the model inputs.

### Network analysis

Graph analysis complements transaction classification by examining relationships between accounts and recorded transfers.

It can help investigators explore connected accounts and potential transaction paths when the source data contains the necessary sender and recipient relationships.

A graph connection must not be presented as proof of a real transfer unless supported by source records.

## 4. Machine Learning Pipeline

The ML workflow consists of the following stages:

1. **Data inspection:** Validate the dataset schema, target labels, missing values, duplicates, and class distribution.
2. **Preprocessing:** Validate input types and handle missing or invalid values consistently.
3. **Feature engineering:** Prepare transaction features and supported historical behavioural features.
4. **Data splitting:** Create training, validation, and final test sets, using chronological splits where appropriate.
5. **Model training:** Train and compare candidate classifiers.
6. **Model selection:** Compare candidate performance using validation data.
7. **Threshold selection:** Choose a suitable decision threshold using validation data.
8. **Evaluation:** Measure precision, recall, F1, PR-AUC, ROC-AUC, and false-positive burden on held-out records.
9. **Model persistence:** Store the model, preprocessing configuration, feature schema, version, and evaluation results.
10. **Inference:** Load the selected model through the FastAPI backend to score transactions.

The final test set must remain untouched during model selection and threshold tuning. Evaluation should be reproducible using the training code and documented configuration.

## 5. Algorithms and Models

The supplied project configuration describes four supervised candidate models and a supplied hybrid model.

**CatBoost Classifier:** A gradient-boosting algorithm for structured data. Its configuration and evaluation should be checked against the actual fitted model.

**XGBoost Classifier:** A gradient-boosting algorithm that can learn nonlinear relationships and interactions between transaction features.

**Random Forest Classifier:** An ensemble of decision trees that provides a useful comparison model for structured transaction data.

**Logistic Regression:** A comparatively simple classification baseline that helps determine whether more complex models provide meaningful improvements.

**Supplied hybrid model:** The setup instructions describe an additional hybrid candidate. Its actual combination logic and measured results should be taken from the bundled implementation and evaluation report.

Models should be compared on the same evaluation data. Model complexity and overall accuracy alone are not sufficient reasons to select a model.

## 6. Feature Engineering

The supplied configuration identifies these model inputs:

- `transaction_amount`
- Transaction hour
- Transaction weekday
- `transaction_type`
- `transaction_direction`
- `channel`
- `merchant_category`
- `account_type`

The actual fitted model's feature schema must be checked before scoring.

Potential additional features, when supported by reliable source data, include recent transaction count, transaction recency, historical amount deviations, and channel usage patterns.

All historical features must be calculated without using future information. Unique transaction identifiers, target labels, and post-investigation outcomes must not be used as predictive features when they introduce leakage.

The supplied application configuration represents absent categorical values as `Unknown`. Missing information may still reduce prediction quality.

## 7. System Architecture

Finsleuth consists of four main layers.

**Frontend:** React and TypeScript provide dashboards, transaction investigation screens, model reports, account-network views, and case workflows.

**Backend:** FastAPI handles authentication, authorization, transaction operations, dataset management, model inference, case management, and audit operations.

**Machine-learning layer:** Python-based components handle preprocessing, trained-model loading, scoring, evaluation artefacts, and prediction explanations where supported.

**Database layer:** MongoDB stores application records and operational information according to the implemented schema.

The main data flow is:

**Dataset → Validation → Feature preprocessing → ML prediction → Analyst investigation → Evidence-backed case → Compliance review → Audit history**

The training dataset and operational database serve different purposes. Importing a dataset does not automatically mean it represents live banking transactions.

## 8. Technology Stack

| Component | Technology | Purpose |
|---|---|---|
| Frontend | React, TypeScript, Vite | Interactive user interface |
| Backend | Python, FastAPI | APIs and application logic |
| Database | MongoDB | Operational data storage |
| Data processing | Pandas, NumPy | Data validation and preprocessing |
| ML framework | scikit-learn | Classification and evaluation |
| Boosting models | CatBoost, XGBoost | Supervised fraud classification |
| Additional model | Random Forest | Ensemble classification |
| Baseline model | Logistic Regression | Baseline comparison |
| Testing | Pytest and frontend test tools | Automated verification |

## 9. Dataset and Data Requirements

The supplied project documentation identifies the bundled banking transactions archive as the primary training and evaluation dataset. It describes approximately 550,000 records, but the exact record count and fraud-label distribution should be confirmed against the archive and the evaluation report.

The project reads the bundled archive using Python's ZIP support. You do not need to manually extract the dataset before running the supplied setup command.

### Required columns for application imports

| Column | Description |
|---|---|
| `transaction_id` | Unique transaction identifier |
| `transaction_date` | Transaction date |
| `transaction_amount` | Transaction amount |
| `is_fraud` | Fraud label, either 0 or 1 |

The optional `transaction_time` column accepts `HH:MM` or `HH:MM:SS`.

For meaningful predictions, provide the model fields `transaction_type`, `transaction_direction`, `channel`, `merchant_category`, and `account_type`.

### Network-analysis requirements

For actual account-network and money-flow analysis, also supply:

- `sender_id`
- `recipient_id`

Both must be supplied on every row when included. Source IDs must be unique across the operational workspace according to the supplied project requirements.

The supplied banking archive does not contain sender/recipient pairs. Its records therefore cannot establish actual account-to-account transfer paths. The fictional graph in demo mode is separate from operational data and must not be treated as real banking evidence.

## 10. User Roles and Features

### Bank Analyst

The analyst investigates potentially suspicious transactions through:

- Transaction alerts and search.
- Transaction detail inspection.
- Risk scores and prediction explanations.
- Available account and transaction-history analysis.
- Account-network exploration where relationship data exists.
- Case creation, investigation notes, and evidence references.
- Case submission for compliance review.

### Risk & Compliance Manager

The manager oversees investigations through:

- Compliance overview.
- Case review and assignment.
- Reassignment and requests for additional evidence.
- Returning, escalating, or closing cases.
- Compliance reporting.
- Audit history and decision review.

Model management and user administration are not part of the manager's role.

### System Administrator

The administrator manages:

- User registrations and access approvals.
- Dataset imports and quality reports.
- Dataset-level access permissions.
- Model evaluation and model versions.
- Model deployment controls where implemented.
- System health, database status, and operational audit events.

The backend must enforce these permissions; hiding a page in the frontend is not sufficient.

## 11. Local Installation and Setup

### Prerequisites

Install:

1. Python 3.13, 64-bit standard build.
2. Node.js with npm.
3. MongoDB Community Server or access to MongoDB Atlas.

MongoDB Compass can be used to inspect the database, but a local MongoDB server must be running if using a local connection.

### Step 1: Open the project folder

Extract the application ZIP into a working directory and open PowerShell in the extracted `Finsleuth` folder, where `manage.py` is located.

```powershell
cd "C:\path\to\Finsleuth"
```

Replace the example path with the actual folder path.

### Step 2: Start MongoDB

For a local MongoDB Community Server installation:

```powershell
Get-Service MongoDB
```

If the service is stopped, open PowerShell as Administrator and run:

```powershell
Start-Service MongoDB
```

Check whether the default port is reachable:

```powershell
Test-NetConnection 127.0.0.1 -Port 27017
```

The expected result is `TcpTestSucceeded : True`.

If using Atlas, verify the connection string, database credentials, and network access configuration.

### Step 3: Configure environment variables if needed

For an existing database or Atlas, copy `backend/.env.example` to `backend/.env` and set:

```dotenv
MONGODB_URI=your_mongodb_connection_string
MONGODB_DATABASE=your_database_name
```

Replace the placeholders with your actual settings. Keep database credentials private.

To preserve existing registrations and investigation records, reuse the same database settings rather than connecting to a new empty database.

### Step 4: Set up Finsleuth

From the project root:

```powershell
python manage.py setup
```

According to the supplied project instructions, setup prepares the database, registers the bundled model candidates, and loads the latest 2,000 unchanged archive records.

Wait for the command to finish. If it fails, resolve the reported error before continuing.

### Step 5: Start the application

Run:

```powershell
python manage.py serve
```

Open:

**http://localhost:8000**

The supplied instructions state that one server serves both the compiled frontend and backend. Do not open `index.html` directly or use an old frontend server on port 5173 for this setup.

## 12. Administrator Login

The designated administrator email is:

`admin@finsleuth.local`

During setup, a random administrator password is generated locally and written to `LOCAL_ADMIN.txt`. The command also prints the file location.

Open that file to retrieve the password. No universal password is shipped with the project.

If you need to reset the designated administrator account, the supplied command is:

```powershell
python manage.py reset-admin
```

Use it only when you intentionally need to reset that account. The supplied instructions state that it revokes the account's sessions while preserving other users and records.

Keep `LOCAL_ADMIN.txt` private and change the password under My profile after signing in.

### Approving registrations

1. Sign in as the operational administrator.
2. Open **Users & approvals**.
3. Select **Review access**.
4. Choose the appropriate active status and permitted role.
5. Enter a rationale.
6. Save the decision.

Demo access is isolated from operational registrations and records.

## 13. How to Use Finsleuth

1. Open `http://localhost:8000`.
2. Sign in using an approved account.
3. Confirm that you are using the correct role-specific workspace.
4. Ask the administrator to grant access to the required operational dataset if it is not visible.
5. Upload and validate transaction data through **Datasets & quality**.
6. Confirm the import after reviewing the quality report.
7. Use **Score records** to score eligible transactions with the deployed model.
8. Open **Transaction alerts** as an analyst and search for a transaction ID.
9. Inspect the prediction and use **Score & explain** where supported.
10. Create a case, record evidence, and submit it for review.
11. Open **Review & assignments** as a compliance manager to review and document the decision.
12. Use the administrator workspace to manage users, datasets, models, and system health.

## 14. Dataset Import and Transaction Scoring

The dataset-import workflow separates validation from scoring.

Before confirming an import, review required columns, data types, invalid values, missing values, duplicate identifiers, fraud-label distribution, rejected rows, source, and licence information.

After importing the dataset, select **Score records** to apply the deployed model to eligible transactions.

The supplied application instructions describe restartable batch scoring. Keep the page open until scoring finishes. If interrupted, clicking again is intended to resume the remaining records.

Keep these concepts separate:

- Source transaction data.
- Dataset-provided fraud labels.
- ML-generated predictions.
- Human investigation decisions.

A model prediction must not silently replace the original dataset label.

## 15. Investigation and Case Management

A typical investigation follows this sequence:

1. Identify a suspicious transaction.
2. Review its risk prediction and contributing features.
3. Examine available transaction history.
4. Explore account relationships if valid sender/recipient data exists.
5. Attach relevant transaction references.
6. Record observations and investigation notes.
7. Submit the case for review.
8. Respond to additional-evidence requests.
9. Document the review outcome.
10. Preserve the audit trail.

Case visibility and permitted actions depend on the authenticated user's role and dataset access.

## 16. Account Network and Money-Flow Analysis

Network analysis is available when suitable account relationships exist in the source data.

It can support connected-account exploration, incoming and outgoing transaction inspection, bounded path searches, chronological transfer views, and investigation of repeated transfer patterns.

Every displayed edge should correspond to a recorded transaction or be explicitly identified as fictional demonstration data.

The supplied primary banking archive lacks sender/recipient pairs, so it cannot establish actual transfer paths. Demo mode provides a fictional connected-account scenario for demonstrating the interface.

## 17. Model Evaluation and Fraud Recall

Fraud detection is an imbalanced classification problem. A model may achieve high overall accuracy while missing a substantial proportion of fraud-labelled transactions.

**Precision** measures how many flagged transactions are positive according to the evaluation labels.

**Recall** measures how many positive-labelled transactions the model identifies.

**F1-score** balances precision and recall.

**PR-AUC** measures the precision-recall trade-off across thresholds and is particularly useful for rare positive classes.

**ROC-AUC** measures the model's ranking ability across thresholds.

**False-positive rate** measures the proportion of legitimate-labelled transactions incorrectly flagged.

Threshold selection must balance missed fraud-labelled transactions against the volume of false alerts.

The supplied project instructions state that no candidate has demonstrated both 85% accuracy and 85% fraud recall on the supplied banking archive. Refer to `MODEL_EVALUATION.md` for the documented measurements.

Do not interpret high accuracy as proof of effective fraud detection. Report held-out results honestly, and do not tune the final test set.

## 18. Database and Access Control

MongoDB stores operational records according to the application's implemented schema.

The supplied project describes dataset-level access lists for active Bank Analysts and Compliance Managers. Administrators choose eligible users during dataset upload and can modify access later.

The backend is expected to enforce these restrictions for transactions, predictions, accounts, graph/trace operations, alerts, cases, evidence, reports, and relevant exports.

Cases involving transactions from multiple datasets should only be visible when the user can access every associated dataset. Access changes should be recorded in the audit history.

Existing datasets may require the administrator to grant access after setup or an upgrade.

## 19. Security and Responsible Use

Finsleuth should be operated with appropriate safeguards for financial information:

- Backend-enforced role-based access.
- Secure password and session handling.
- Controlled registration approval.
- Environment-based database credentials.
- Validated dataset imports.
- Dataset-level access restrictions.
- Traceable administrative and case-management actions.
- Restricted exports and evidence access.

Do not commit `.env`, `LOCAL_ADMIN.txt`, passwords, session tokens, or database credentials to source control.

A model prediction is not proof of fraud. An unusual transaction or account connection does not independently establish fraudulent intent. Actual transaction paths must be grounded in recorded transfers.

## 20. Testing

### Backend tests

From the project root:

```powershell
cd backend
python -m pip install -r requirements-test.txt
python -m pytest -q
```

### Frontend tests and production build

From the `frontend` directory:

```powershell
npm test
npm run build
```

### Browser checks

The supplied project documents a browser QA script:

```powershell
python scripts/browser_qa.py
```

Playwright Chromium must be installed for the browser checks.

Record the actual result of each command. Mocked database tests do not prove that live MongoDB connectivity or all end-to-end workflows work.

## 21. Project Structure

```text
Finsleuth/
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   └── components/
│   └── e2e/
├── backend/
│   ├── app/
│   ├── ml/
│   └── tests/
├── artifacts/
│   ├── dataset/
│   └── runtime/
├── data/
│   └── archive.zip
├── scripts/
│   └── browser_qa.py
├── manage.py
├── README.md
├── RELEASE_REPORT.md
└── MODEL_EVALUATION.md
```

This is a high-level view based on the supplied project documentation. The actual project archive is the definitive source for its current files and directories.

Important files:

- `manage.py`: setup, local server startup, and administrator recovery.
- `backend/app`: APIs, authentication, database operations, and case workflows.
- `backend/ml`: data loading, model preparation, training, validation, and inference.
- `backend/tests`: backend automated tests.
- `frontend/src/pages`: role-specific pages.
- `frontend/src/components`: shared UI components.
- `frontend/e2e`: browser workflow checks.
- `artifacts/dataset`: supplied model artefacts and evaluation reports.
- `data/archive.zip`: bundled transaction archive.
- `RELEASE_REPORT.md`: recorded checks and remaining gaps.
- `MODEL_EVALUATION.md`: measured model results.

## 22. Limitations

1. The supplied documentation does not establish that the current models achieve both 85% accuracy and 85% fraud recall.
2. Class imbalance can make accuracy misleading.
3. Fraud-label quality and real-world generalisation require validation.
4. The supplied banking archive lacks sender/recipient pairs and cannot establish actual transfer paths.
5. Missing model inputs can reduce prediction quality.
6. Fictional demonstration records must remain separate from operational data and training.
7. The supplied setup does not automatically connect to a live bank or payment network.
8. Password-recovery email requires separate SMTP configuration.
9. Application and integration behaviour must be verified in the actual environment before being described as fully working.

Consult `RELEASE_REPORT.md` and `MODEL_EVALUATION.md` for the recorded verification status and measured model results.

## 23. Future Enhancements

Potential improvements include more robust transaction-history features, better fraud recall at an acceptable false-positive rate, improved model calibration, more comprehensive model monitoring, stronger evidence summaries, graph analysis using reliable relationship data, improved import-quality reporting, and expanded end-to-end testing.

These are potential enhancements, not claims that every feature is already implemented.

---

## Conclusion

Finsleuth combines machine-learning-based transaction-risk scoring with explainability, investigation workflows, account-network analysis, and compliance review.

Its central objective is to connect predictions with evidence, allowing analysts to investigate suspicious activity and compliance managers to review documented findings.

#Datasets Used:
1. Banking Transactions 2019–2024 — Indian Banking Transactions
https://www.kaggle.com/datasets/belbino/indian-banking-transactions-20192024
2. PaySim — Synthetic Financial Transactions
https://www.kaggle.com/datasets/ealaxi/paysim1
The system supports investigation prioritisation and human decision-making. Its effectiveness depends on the quality of the supplied data, measured fraud recall, manageable false-positive rates, and verified application functionality.
