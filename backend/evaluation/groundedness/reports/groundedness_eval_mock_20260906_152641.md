# Groundedness Evaluation — mock

- Dataset: `C:\Users\karti\OneDrive\Desktop\Projects\BYOK\backend\evaluation\groundedness\datasets\groundedness_baseline.json` v1.0
- Total: 50 Accuracy: 0.420
- Precision: 0.420 Recall: 0.420 F1: 0.420
- Unsupported Recall: 0.700 Contradicted Recall: 0.182
- Latency P50 0.02ms

## Confusion Matrix

| Expected | SUPPORTED | PARTIALLY_SUPPORTED | UNSUPPORTED | CONTRADICTED | UNCERTAIN | NON_VERIFIABLE |
|---|---|---|---|---|---|---|
| SUPPORTED | 12 | 0 | 3 | 0 | 0 | 0 |
| PARTIALLY_SUPPORTED | 6 | 0 | 1 | 0 | 0 | 0 |
| UNSUPPORTED | 2 | 0 | 7 | 1 | 0 | 0 |
| CONTRADICTED | 6 | 0 | 3 | 2 | 0 | 0 |
| UNCERTAIN | 1 | 0 | 2 | 0 | 0 | 0 |
| NON_VERIFIABLE | 3 | 0 | 1 | 0 | 0 | 0 |
