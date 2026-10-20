# Measured model evaluation

The five supplied models were loaded and their historical test results recomputed on Python 3.13.16. No model has demonstrated both 85% accuracy and 85% fraud recall. This does not prove that improvement is impossible.

Source: unchanged data/archive.zip; 550,000 rows. Test: 82,696 rows, 724 fraud-labelled records. The test split has been evaluated previously; it is not a new untouched holdout.

| Supplied model / saved threshold | Accuracy | Fraud recall | Precision | False alerts |
|---|---:|---:|---:|---:|
| Logistic Regression | 23.70% | 78.31% | 0.89% | 62,943 |
| Random Forest | 18.83% | 83.43% | 0.89% | 67,002 |
| XGBoost | 23.85% | 76.10% | 0.87% | 62,802 |
| CatBoost | 19.97% | 80.66% | 0.88% | 66,044 |
| Hybrid (CatBoost + Random Forest) | 86.74% | 19.61% | 1.35% | 10,382 |

These are the default thresholds in each supplied artifact. Existing databases retain their deployment; fresh setup selects the model with the highest saved validation PR-AUC. The hybrid is not automatically the active model. Administrators may approve and deploy another artifact. Raising recall by flagging nearly every record is not an acceptable quality improvement.

The full reproduced metrics include F1, PR-AUC, ROC-AUC, specificity, false-positive rate, confusion matrices, false negatives by channel and median amount, and recall/false alerts at 1%, 2% and 5% review budgets: artifacts/evaluation/reproduced_metrics.json. Source labels and examples were not changed.

## Additional experiments
The completed CatBoost experiments in the saved JSON add customer context and strictly earlier customer history. Simultaneous customer transactions are aggregated before computing history, so an event cannot see another event at the same timestamp. Thresholds maximize validation recall subject to validation accuracy of at least 85%. Reports are in artifacts/evaluation/joint_benchmark.json. Experimental artifacts are not automatically deployed and are not drop-in replacements for the eight-feature serving pipeline.

## Reproduce
From the project folder, with backend dependencies installed:
```bash
PYTHONPATH=backend python -m ml.verify_evaluation
PYTHONPATH=backend python -m ml.joint_benchmark data/archive.zip artifacts/evaluation
```
On Windows PowerShell set `$env:PYTHONPATH="backend"` before the `python -m ...` commands.

The existing four-candidate training pipeline remains available through Admin → Datasets → Train models. It trains Logistic Regression, Random Forest, XGBoost and CatBoost using the same preprocessing at inference. Local explanations use exact interventional Shapley values with an additivity check. No training on invented samples was introduced. The supplied dataset’s real-bank provenance has not been independently verified.

The separately supplied Fraud Detection Dataset archive has a different card-payment schema and is not used or silently substituted in this release; its inspection is recorded separately. Training and integrating that additional dataset remain incomplete.

## Retrained experiments: final measured results

| Candidate | Test accuracy | Fraud recall | Precision | False alerts |
|---|---:|---:|---:|---:|
| Context + history / unweighted | 81.14% | 25.28% | 1.20% | 15,055 |
| Context + history / balanced | 84.01% | 22.65% | 1.28% | 12,662 |

Both validation-selected history experiments missed the joint 85% target on the historical test partition. Their .cbm artifacts are included for reproducibility; neither replaces the serving pipeline. The comparison is between different fixed operating points, not proof of a general improvement.
