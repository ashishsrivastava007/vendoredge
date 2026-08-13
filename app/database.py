"""
Database connection helper. Implements the pattern specified in the threat model:
app.current_org_id must be set from the verified JWT claim at the START of every
request, on every connection acquired from the pool — never assumed to persist,
never taken from unvalidated input. This is the actual code behind the
cross-tenant-leakage mitigation, not just a principle.
"""
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager


def _get_dsn() -> str:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL not set. Add it to your .env file.")
    return dsn


@contextmanager
def get_org_scoped_connection(organisation_id: str):
    """
    Yields a connection with app.current_org_id set for this request only.
    Every route handler must use this, never a raw connection, or RLS
    isolation silently doesn't apply.
    """
    conn = psycopg2.connect(_get_dsn(), cursor_factory=RealDictCursor)
    try:
        with conn.cursor() as cur:
            # Parameterized even though it's a session variable, not user data directly —
            # org_id here must already be verified against the JWT before this is called,
            # never passed straight from a request body/header.
            cur.execute("SET app.current_org_id = %s", (organisation_id,))
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()  # closing (not just returning to a pool) for MVP simplicity;
        # revisit with an explicit RESET on return once real connection pooling
        # (e.g. pgbouncer) is introduced at scale, per the threat model's defense-in-depth note.
