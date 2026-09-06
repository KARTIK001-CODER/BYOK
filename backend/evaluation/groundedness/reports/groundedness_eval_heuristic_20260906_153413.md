# Groundedness Evaluation — heuristic

- Dataset: `C:\Users\karti\OneDrive\Desktop\Projects\BYOK\backend\evaluation\groundedness\datasets\groundedness_baseline.json` v1.0
- Total: 50 Accuracy: 0.620
- Precision: 0.620 Recall: 0.620 F1: 0.620
- Unsupported Recall: 0.400 Contradicted Recall: 0.727
- Latency P50 0.04ms

## Confusion Matrix

| Expected | SUPPORTED | PARTIALLY_SUPPORTED | UNSUPPORTED | CONTRADICTED | UNCERTAIN | NON_VERIFIABLE |
|---|---|---|---|---|---|---|
| SUPPORTED | 9 | 4 | 1 | 1 | 0 | 0 |
| PARTIALLY_SUPPORTED | 0 | 6 | 0 | 1 | 0 | 0 |
| UNSUPPORTED | 0 | 1 | 4 | 5 | 0 | 0 |
| CONTRADICTED | 0 | 2 | 1 | 8 | 0 | 0 |
| UNCERTAIN | 0 | 0 | 3 | 0 | 0 | 0 |
| NON_VERIFIABLE | 0 | 0 | 0 | 0 | 0 | 4 |
