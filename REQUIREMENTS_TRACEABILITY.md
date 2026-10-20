# Requirements traceability

| Requirement | Implementation / evidence | Status |
|---|---|---|
| MongoDB, no Docker, Python 3.13 | backend/app/db.py, requirements, manage.py; fitted models loaded under 3.13.16 | Implemented; live Mongo/Windows unverified |
| Analyst transaction investigation and explanations | transactions.py, Investigation.tsx, exact Shapley pipeline; workflow tests | Implemented |
| Account graph and money-flow paths | graph/trace API, Cytoscape/DemoNetwork | Conditional on real sender/recipient data |
| Manager reviews, assignment, reporting | cases.py, CaseWorkspace.tsx, operations.py | Implemented; automated workflows tested |
| Admin-only model management | admin.py, operations.py, main.tsx RoleGate | Fixed; denial tests added |
| User registration and approvals | auth.py, bootstrap.py, UsersPage; approval tests | Implemented |
| Readable audited events | admin.audit_list, AuditPage; date/action filters | Fixed |
| Demo isolation and dashboards | services.seed_demo and scope checks | Implemented; fictional case/graph labels retained |
| Word logo and UI references | Exact image2.png match; existing light dashboard layouts, revised audit | Partial; not pixel-exact plan parity |
| Original ZIP training input | ml/data.py uses zipfile streams; original archive preserved | Implemented |
| Four candidate models and hybrid | Saved artifacts + pipeline.py and hybrid.py | Reproduced; original four retrain in workflow test |
| High fraud recall and high accuracy | reproduced_metrics.json, joint_benchmark.json | Not achieved |
| Review budgets / false negatives | ml/verify_evaluation.py | Implemented diagnostics |
| Additional card-payment dataset | additional_dataset_inspection.json | Inspected; training/integration incomplete |
| Browser, build and backend verification | TEST_RESULTS.md | Actual run results recorded |
| Production backups, SMTP, TLS, load verification | Configuration/deployment responsibilities | Not fully implemented/verified |
