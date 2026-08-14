import os

# Existing integration tests predate signed workspace sessions. They exercise
# the legacy private-link compatibility path; production defaults it OFF.
os.environ.setdefault("VENDOREDGE_AUTH_SECRET", "test-secret-for-vendoredge-auth-longer-than-32")
os.environ.setdefault("ALLOW_LEGACY_WORKSPACE_LINKS", "true")
os.environ.setdefault("VALIDATION_ENABLED", "true")


# Test database wiring is deliberately separate from production DATABASE_URL.
# CI/local test runs must provide TEST_DATABASE_URL explicitly; DB-backed tests
# are skipped when it is absent rather than guessing credentials.
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
if TEST_DATABASE_URL:
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
else:
    os.environ.pop("DATABASE_URL", None)

_DB_TEST_MODULES = {
    "test_async_reasoning_adversarial.py",
    "test_claim_integrity.py",
    "test_confidence_calibration.py",
    "test_evidence_gate_backfill.py",
    "test_evidence_provenance.py",
    "test_integration_full_flow.py",
    "test_no_contradiction.py",
    "test_red_team.py",
    "test_stress_test_bypass.py",
    "test_supplier_freight_and_leakage.py",
    "test_tenant_isolation.py",
    "test_validation_page.py",
}

def pytest_collection_modifyitems(config, items):
    if TEST_DATABASE_URL:
        return
    import pytest
    skip_db = pytest.mark.skip(reason="DB-backed test requires TEST_DATABASE_URL")
    for item in items:
        if item.fspath.basename in _DB_TEST_MODULES:
            item.add_marker(skip_db)
