# Groundedness Evaluation — heuristic

- Dataset: `C:\Users\karti\OneDrive\Desktop\Projects\BYOK\backend\evaluation\groundedness\datasets\groundedness_baseline.json` v1.0
- Total: 50 Accuracy: 0.580
- Precision: 0.580 Recall: 0.580 F1: 0.580
- Unsupported Recall: 0.700 Contradicted Recall: 0.182
- Latency P50 0.04ms

## Confusion Matrix

| Expected | SUPPORTED | PARTIALLY_SUPPORTED | UNSUPPORTED | CONTRADICTED | UNCERTAIN | NON_VERIFIABLE |
|---|---|---|---|---|---|---|
| SUPPORTED | 9 | 5 | 1 | 0 | 0 | 0 |
| PARTIALLY_SUPPORTED | 0 | 7 | 0 | 0 | 0 | 0 |
| UNSUPPORTED | 0 | 3 | 7 | 0 | 0 | 0 |
| CONTRADICTED | 2 | 5 | 2 | 2 | 0 | 0 |
| UNCERTAIN | 0 | 0 | 3 | 0 | 0 | 0 |
| NON_VERIFIABLE | 0 | 0 | 0 | 0 | 0 | 4 |
