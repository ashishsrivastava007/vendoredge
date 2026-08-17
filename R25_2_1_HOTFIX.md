# VendorEdge R25.2.1 — Production Hotfix

## Incident

The first live Holy Shit Test exposed a production failure during quote-comparison normalization.

The classifier returned `number_of_suppliers_being_compared` as a JSON number (`2`). The normalized evidence model defined that field as a human-readable string. Pydantic v2 correctly rejected the integer instead of silently coercing it, and the case request surfaced the generic production error page.

## Root cause

A type-boundary mismatch between LLM extraction output and the normalized evidence schema:

- classifier output: numeric scalar (`2`)
- normalized schema: `Optional[str]`
- Pydantic v2: rejects the integer for a string field

## Fix

The normalization boundary now accepts numeric scalars for all human-readable quote-comparison evidence fields and converts them to strings before downstream processing.

Lists/dicts are intentionally not coerced because they indicate a real schema mismatch that should remain visible.

This preserves the existing normalized evidence contract while making the LLM → deterministic normalization boundary robust to valid JSON scalar typing.

## Regression coverage

Added tests for:

- numeric supplier count (`2` → `"2"`)
- numeric price scalar (`45.5` → `"45.5"`)
- numeric lead-time scalar (`35` → `"35"`)
- direct `normalize_evidence()` execution with numeric supplier count

Targeted cumulative suite after the fix: **48 passed**.

Python compilation: **passed**.

Full DB/Anthropic-dependent suite remains environment-dependent in this local validation environment and is executed by CI / deployment environment.
