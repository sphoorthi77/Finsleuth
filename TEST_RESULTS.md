# Checks executed — 20 October 2026

- Python compilation: passed for backend modules and manage.py.
- Python 3.13.16 artifact inference: all five supplied models loaded and returned finite, bounded probabilities; thresholds matched saved reports.
- Frontend unit tests: 9 passed (2 files).
- TypeScript + production Vite build: passed, including the final audit and dashboard changes. Warning: JavaScript chunk exceeds 500 kB.
- Backend workflows: initial run 16 passed, 1 failed solely because the inherited test expected four models while the supplied archive contains five. That expectation was corrected and the affected test rerun; see status below.
- Full workflow run included actual training of the four candidate models on 30,000 original archive records, registry approval/deployment, prediction/explanation additivity, auth approvals, sessions, recovery, case review, dataset import/scoring, graph/trace, scope isolation and admin-only model/audit permissions.
- Backend persistence in these tests: explicitly gated mongomock, not a live MongoDB server. No live MongoDB server was installed/verified here.
- Browser: five tests attempted; all blocked at browser launch by Operation not permitted for Chromium socket creation. No application interaction or fresh screenshot validation completed in this run. Do not count these as passing.
- Model evaluation: all five supplied artifacts reproduced on the historical test partition. Repeated holdout evaluation is explicitly labelled as such. Review-budget and false-negative diagnostics saved.
- Word logo: byte-for-byte match with embedded word/media/image2.png. New Word file is identical to the previously read plan.
- Windows: not executed on a Windows host.

Backend targeted rerun: 1 passed in 72.45 seconds. Combined result: all 17 distinct backend tests passed, with the one corrected test rerun separately.

Both full-archive customer-history experiments completed; artifacts and validation/test reports are included. Neither achieved the joint target.

Release safety tests: 2 passed, covering simultaneous-event/future-history exclusion and unique, idempotent local administrator credentials. Total distinct backend tests passed across the runs: 19. An initial invocation from the wrong directory could not import ml; rerunning from backend (as documented) passed.
