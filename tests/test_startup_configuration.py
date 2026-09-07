import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "app" / "main.py"
DATABASE = ROOT / "app" / "database.py"
SEED = ROOT / "app" / "seed.py"


def _source(path):
    return path.read_text(encoding="utf-8")


def test_database_validation_exists_and_checks_required_urls():
    source = _source(DATABASE)
    tree = ast.parse(source)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "validate_database_configuration")
    body = ast.unparse(fn)
    assert "DATABASE_URL" in body
    assert "MIGRATION_DATABASE_URL" in body
    assert "connect_timeout=10" in body
    assert "SELECT 1" in body


def test_production_lifespan_validates_database_before_migrations():
    source = _source(MAIN)
    tree = ast.parse(source)
    fn = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "lifespan")
    calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)]
    names = [n.func.id for n in calls if isinstance(n.func, ast.Name)]
    assert "_secret" in names
    assert "validate_database_configuration" in names
    assert "run_migrations" in names
    source_body = ast.unparse(fn)
    assert source_body.index("validate_database_configuration") < source_body.index("run_migrations")


def test_production_requires_migration_url_and_app_url_is_mandatory():
    source = _source(MAIN)
    assert 'require_migration_url=os.environ.get("ENVIRONMENT", "").lower() in {"production", "prod"}' in source
    source_db = _source(DATABASE)
    assert 'os.environ.get("DATABASE_URL")' in source_db
    assert 'raise RuntimeError("DATABASE_URL not set' in source_db


def test_demo_org_setup_no_longer_allows_known_database_failure_to_start_healthy():
    source = _source(MAIN)
    assert "Database connectivity was not stable enough to complete demo organisation setup" in source
    assert "application startup aborted" in source
    assert "The app will start, but every request will fail" not in source


def test_render_blueprint_declares_database_wiring_and_auth_secret():
    source = _source(ROOT / "render.yaml")
    assert "key: DATABASE_URL" in source
    assert "key: MIGRATION_DATABASE_URL" in source
    assert "name: vendoredge-db" in source
    assert "key: VENDOREDGE_AUTH_SECRET" in source
    assert "generateValue: true" in source
