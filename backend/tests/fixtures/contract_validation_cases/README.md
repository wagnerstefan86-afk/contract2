# Contract Validation Cases

Golden testset for validating the 2-stage pipeline (risk_screen + deep_checks).

## Format

Each `.json` file contains an array of validation cases. Schema per case:

```json
{
  "case_id": "P01_REGULATORY_SHIFT",
  "short_name": "Regulatory burden transfer",
  "case_type": "single_clause",
  "clause_text": "Der Auftragnehmer stellt jederzeit ...",
  "expected_problematic": true,
  "expected_problem_types": ["regulatory_shift"],
  "expected_trigger_domains": ["regulatory"],
  "expected_severity_min": "medium",
  "expected_theme_keywords": ["regulatorisch", "anpassung", "kosten"],
  "forbidden_theme_keywords": ["Compliance"],
  "notes": "Classic regulatory passthrough without cost cap."
}
```

## Case types

- `single_clause`: One clause evaluated in isolation
- `mini_contract`: Multiple clauses forming a mini-contract (tests cross-clause interaction)

## Naming convention

- `P##_*` — Positive cases (must be flagged as problematic)
- `N##_*` — Negative cases (must NOT be flagged)

## Running validation

```bash
python -m pytest backend/tests/test_validation_runner.py -v
# or
python backend/tests/run_clause_validation.py
```
