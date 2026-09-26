# VendorEdge — Release Candidate Manifest

## Identity

- **Archive**: `VendorEdge_RELEASE_CANDIDATE_1023TESTS_20260925.zip`
- **SHA-256**: `757a351ddecbc8b18bce697ee0962da0e137a70075bf70d0c48e45cbb3cce7ee`
- **Archive size**: 984,072 bytes (964 KB)
- **Total files packaged**: 362
- **Packaged**: 2026-09-25
- **Purpose**: Candidate build for independent adversarial validation. No functionality changes were made during packaging.

No version-control system exists in this environment (confirmed: not a git repository), so this content-hash is the release's sole immutable identifier — verify it against the archive before use.

## Verification Performed

1. **Source regression** (working directory, pre-packaging): `1023 passed`.
2. **Staged-copy byte-identity check**: `diff -rq` between the working directory and the staged release content (excluding only the artifacts listed below) returned zero differences.
3. **Staged-copy regression**: the test suite was re-run from the staged copy itself — `1023 passed` — confirming the exact content about to be archived is the passing state, not merely the original working directory.
4. **Archive integrity**: `unzip -t` reported no errors across all 362 entries.
5. **Archive entry count**: 362 files inside the archive, matching the staged file count exactly.
6. **Archive exclusion check**: zero `__pycache__`, `.pyc`, or `.pytest_cache` entries present inside the archive.
7. **Fresh-extraction regression** (the strongest check): the archive was extracted to a completely clean location and the test suite was run directly from that extraction — `1023 passed`. This proves the delivered ZIP itself works, not just the pre-archive staging directory.

Every check above passed on the first attempt; no code was modified at any point in this packaging process.

## Contents

| Directory | Files | Contents |
|---|---|---|
| `app/` | 96 | Application source — routes, pipeline modules (including `market_signal_intelligence.py`, the evidence-grounding layer), models, static frontend |
| `db/` | 2 | `schema.sql` and related database definitions |
| `tests/` | 147 | 142 `test_*.py` files (1,023 tests) plus `conftest.py`, `__init__.py`, and the shared `_market_signal_intelligence_verifier_fixture.py` fixture |
| `benchmark/` | 5 | Stress-test harness and benchmark scripts |
| (root) | 112 | Config (`Dockerfile`, `docker-compose.yml`, `render.yaml`, `requirements.txt`, `requirements-dev.txt`, `.env.example`, `.env.test.example`, `.dockerignore`) and documentation (`README.md`, `ARCHITECTURE.md`, and the accumulated `CTO_RELEASE_*.md` / `RELEASE_*_MANIFEST.json` history from prior work on this codebase) |

**Excluded** (transient/generated, not source): `__pycache__/` directories, `*.pyc`/`*.pyo`/`*.pyd` files, `.pytest_cache/`. Nothing else was excluded — this is the complete working tree as it stood at packaging time.

## Test Command

```
DATABASE_URL="postgresql://vendoredge_app:<password>@<host>:5432/<db>" \
TEST_DATABASE_URL="postgresql://vendoredge_app:<password>@<host>:5432/<db>" \
MIGRATION_DATABASE_URL="postgresql://postgres:<password>@<host>:5432/<db>" \
VENDOREDGE_AUTH_SECRET="<32+ char secret>" \
ANTHROPIC_API_KEY="<placeholder or real key — deterministic tests don't require a real one>" \
ALLOW_LEGACY_WORKSPACE_LINKS="true" \
pytest -q
```

Expected result: `1023 passed`.

## Known, Previously-Disclosed Limitations (carried forward, not resolved by packaging)

This candidate build includes the Evidence Grounding Layer for Market Signal Intelligence (a two-layer deterministic + semantic grounding mechanism) and its closure of two specific gaps (implication-side temporal grounding; strengthened scope/geography subset grounding). Limitations already disclosed in the implementation reports for this work remain true and are not restated in full here — see the prior implementation reports for: lexicon-coverage boundaries (word-form gaps, small region/marker lists), the unproven real-model behavior of the semantic (Layer 2) grounding calls (no live API key exists in this environment), and causal/entitlement grounding remaining marker-presence-only.

## Explicit Statement

This archive is a packaging artifact only. No source code was modified to produce it. It is presented as the candidate build for independent adversarial validation — not as a claim of production-readiness, completeness, or "world-class" status.
