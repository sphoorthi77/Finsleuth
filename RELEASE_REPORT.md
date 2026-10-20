# Release report — 20 October 2026

This release fixes the supplied Finsleuth_Final.zip. It is not a claim that every original-plan requirement or the joint 85% accuracy/recall target is complete.

## Corrections implemented
- Removed Model Performance from manager navigation; backend model registry and monitoring now return 403 to managers. Frontend role gates also prevent direct model/admin URL access.
- Replaced raw JSON audit entries with readable descriptions, recorded actor names, timestamps, affected-case titles, manager case links, expandable fields, action filtering, and inclusive UTC date filtering. Invalid/reversed dates return 422.
- Traced case.demo_example to backend demo seeding. Existing seeded events are preserved and labelled as demonstration events; illustrative entries are suppressed from operational audit responses. Actual events remain database-backed.
- Fixed hybrid report crash caused by absent global_importance. Added accuracy alongside recall, precision and false-positive metrics. Clarified that saved-default report thresholds differ from custom deployments.
- Removed hardcoded CatBoost performance claims from the analyst dashboard. Unscored transactions now display Not scored rather than an invented zero-risk value.
- Removed the shared administrator password from the distributable. Setup creates a unique local password and prints the credentials-file location. Existing accounts are preserved; explicit reset-admin recovers access without clearing data.
- Corrected the password-recovery fallback URL to the actual port 8000.
- Reproduced the five supplied models, added review-budget and false-negative diagnostics, and corrected simultaneous-event leakage in the experimental history features.

## UI reference evidence
The newly supplied Word document is byte-identical to the earlier plan. Its 45 embedded reference images were inspected via the contact sheet. The shipped logo exactly matches word/media/image2.png. Existing landing city/network illustration, white/navy/teal dashboard cards, investigation table/detail split, network canvas and role workspaces were retained. Audit layout was revised using the readable event/actor/filter hierarchy of the audit reference. This is not a pixel-exact recreation of every embedded reference; no such claim is made.

## Remaining gaps / deployment limits
- No verified model meets both 85% accuracy and 85% fraud recall. Experimental history models are not integrated into production inference because their schema differs and their measured results do not establish the required quality.
- The separately supplied card-payment dataset has been inspected but is not trained or integrated in this package. The original banking archive remains the operational training source.
- Original records have no sender/recipient transfer pairs. Operational mule graphs and temporal paths require those fields in your uploaded data. Demo has a clearly fictional interactive graph, isolated from training.
- Live MongoDB and Windows runtime checks were not available in this environment; integration tests use explicitly gated mongomock. MongoDB is still required for the actual application. No Docker is included.
- SMTP delivery needs a configured provider. Production TLS, MongoDB backups, monitoring infrastructure and hosting credentials are not automatically provisioned.
- Scheduled jobs assume one API worker. Full-scale million-record load testing has not been performed.
- UI parity for all reference screenshots and complete plan-wide functionality are not verified. The frontend bundle has a size warning; its build succeeds.

## Admin access
Email: admin@finsleuth.local. Run python manage.py setup, then open the generated LOCAL_ADMIN.txt for your unique password. If an older account uses another password, run python manage.py reset-admin. Approve pending users in the operational administrator workspace, not the isolated demo.

## Verification
See TEST_RESULTS.md for the exact checks executed. Browser checks were attempted, but Chromium could not launch because this environment denied a required socket operation. They are not counted as passing. The test harness uses a mock MongoDB, not a live database.
