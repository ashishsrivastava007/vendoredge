"""
Creates one default demo organisation + user automatically, if they don't
already exist -- so a non-technical founder never has to type a database
command just to try the product.

Also runs the ENTIRE schema.sql file at every app startup. This replaced an
earlier, narrower approach (a small hand-maintained list of "catch up"
changes) once it became clear that relying on Docker's auto-init trick
(docker-entrypoint-initdb.d) doesn't exist on real hosting providers --
their managed Postgres offerings don't run any init script automatically.
Since schema.sql is written to be fully idempotent (every statement uses
IF NOT EXISTS / existence checks), running the whole file on every single
startup is safe whether the database is brand new (creates everything) or
already up to date (does nothing) -- this is what makes deploying to any
new host require zero manual database commands from a non-technical founder.
"""
import os
import psycopg2
from psycopg2 import sql

DEMO_ORG_ID = "00000000-0000-0000-0000-000000000001"
DEMO_USER_ID = "00000000-0000-0000-0000-000000000002"

_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "..", "db", "schema.sql")


def _provision_app_role(conn):
    """Provision the non-superuser application role from deployment-time secrets.

    No application password is stored in schema.sql or source control. The
    migration connection must be privileged enough to create/alter roles; if
    APP_DATABASE_PASSWORD is absent, role provisioning is skipped so an
    externally-managed application role can be used unchanged.
    """
    password = os.environ.get("APP_DATABASE_PASSWORD")
    if not password:
        return
    role_name = os.environ.get("APP_DATABASE_USER", "vendoredge_app")
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role_name,))
        exists = cur.fetchone() is not None
        if not exists:
            cur.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD %s").format(sql.Identifier(role_name)),
                (password,),
            )
        else:
            cur.execute(
                sql.SQL("ALTER ROLE {} LOGIN PASSWORD %s").format(sql.Identifier(role_name)),
                (password,),
            )


def run_migrations():
    """
    Runs the full, idempotent schema.sql against the database. Deliberately
    uses a SEPARATE, more privileged connection (MIGRATION_DATABASE_URL)
    rather than the app's everyday DATABASE_URL -- the ordinary app account
    is intentionally restricted (no schema-altering rights) as a security
    measure, so it genuinely cannot run this even if it wanted to. That's
    the correct day-to-day security posture; schema setup needs its own,
    narrowly-used, more privileged connection.
    """
    dsn = os.environ.get("MIGRATION_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not dsn:
        return
    with open(_SCHEMA_PATH) as f:
        schema_sql = f.read()

    conn = psycopg2.connect(dsn)
    try:
        _provision_app_role(conn)
        with conn.cursor() as cur:
            cur.execute(schema_sql)
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"FATAL: schema setup/migration failed ({e}); startup must not continue against an unknown schema.")
        raise
    finally:
        conn.close()


def ensure_demo_org_exists():
    """Create the demo workspace through the same tenant-scoped app path.

    The deterministic demo ID is used as the initial tenant context, so this
    works even with FORCE RLS and does not require the everyday app connection
    to be a superuser.
    """
    if not os.environ.get("DATABASE_URL"):
        return
    from app.database import get_org_scoped_connection

    with get_org_scoped_connection(DEMO_ORG_ID) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM organisations WHERE id = %s", (DEMO_ORG_ID,))
            if cur.fetchone():
                return
            cur.execute(
                "INSERT INTO organisations (id, name) VALUES (%s, 'Demo Organisation')",
                (DEMO_ORG_ID,),
            )
            cur.execute(
                "INSERT INTO users (id, organisation_id, email, password_hash) "
                "VALUES (%s, %s, 'demo@vendoredge.dev', 'not-a-real-password-yet')",
                (DEMO_USER_ID, DEMO_ORG_ID),
            )

