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

DEMO_ORG_ID = "00000000-0000-0000-0000-000000000001"
DEMO_USER_ID = "00000000-0000-0000-0000-000000000002"

_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "..", "db", "schema.sql")


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
        with conn.cursor() as cur:
            cur.execute(schema_sql)
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Warning: schema setup/migration failed ({e}); continuing anyway, "
              f"but the database may be out of date or missing tables.")
    finally:
        conn.close()


def ensure_demo_org_exists():
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        return
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM organisations WHERE id = %s", (DEMO_ORG_ID,))
            if cur.fetchone():
                return  # already seeded, nothing to do
            cur.execute(
                "INSERT INTO organisations (id, name) VALUES (%s, 'Demo Organisation')",
                (DEMO_ORG_ID,),
            )
            cur.execute("SET app.current_org_id = %s", (DEMO_ORG_ID,))
            cur.execute(
                "INSERT INTO users (id, organisation_id, email, password_hash) "
                "VALUES (%s, %s, 'demo@vendoredge.dev', 'not-a-real-password-yet')",
                (DEMO_USER_ID, DEMO_ORG_ID),
            )
        conn.commit()
    finally:
        conn.close()
