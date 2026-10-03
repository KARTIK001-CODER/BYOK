# Groundedness Evaluation — heuristic

- Dataset: `C:\Users\karti\OneDrive\Desktop\Projects\BYOK\backend\evaluation\groundedness\datasets\groundedness_baseline.json` v1.0
- Total: 50 Accuracy: 0.460
- Precision: 0.460 Recall: 0.460 F1: 0.460
- Unsupported Recall: 0.900 Contradicted Recall: 0.182
- Latency P50 0.04ms

## Confusion Matrix

| Expected | SUPPORTED | PARTIALLY_SUPPORTED | UNSUPPORTED | CONTRADICTED | UNCERTAIN | NON_VERIFIABLE |
|---|---|---|---|---|---|---|
| SUPPORTED | 6 | 7 | 2 | 0 | 0 | 0 |
| PARTIALLY_SUPPORTED | 0 | 6 | 1 | 0 | 0 | 0 |
| UNSUPPORTED | 0 | 1 | 9 | 0 | 0 | 0 |
| CONTRADICTED | 2 | 4 | 3 | 2 | 0 | 0 |
| UNCERTAIN | 0 | 0 | 3 | 0 | 0 | 0 |
| NON_VERIFIABLE | 0 | 0 | 4 | 0 | 0 | 0 |
