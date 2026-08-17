"""Tenant-scoped PostgreSQL access for VendorEdge.

All application queries use a bounded connection pool. Tenant context is applied
with SET LOCAL inside the transaction, so the context cannot leak when a
connection is returned to the pool. The migration/seed path is intentionally
separate and may use its privileged migration connection.
"""
import os
from contextlib import contextmanager
from threading import Lock

from psycopg2 import pool
from psycopg2 import OperationalError, InterfaceError
from psycopg2.extras import RealDictCursor

_POOL: pool.ThreadedConnectionPool | None = None
_POOL_LOCK = Lock()


def _get_dsn() -> str:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL not set. Add it to your .env file.")
    return dsn


def _pool_bounds() -> tuple[int, int]:
    minimum = max(1, int(os.environ.get("VENDOREDGE_DB_POOL_MIN", "1")))
    maximum = max(minimum, int(os.environ.get("VENDOREDGE_DB_POOL_MAX", "10")))
    return minimum, maximum


def _get_pool() -> pool.ThreadedConnectionPool:
    global _POOL
    if _POOL is None:
        with _POOL_LOCK:
            if _POOL is None:
                minimum, maximum = _pool_bounds()
                _POOL = pool.ThreadedConnectionPool(
                    minimum,
                    maximum,
                    dsn=_get_dsn(),
                    cursor_factory=RealDictCursor,
                )
    return _POOL


@contextmanager
def get_org_scoped_connection(organisation_id: str):
    """Yield a pooled connection scoped to one verified organisation.

    ``SET LOCAL`` makes the tenant identity transaction-local. We always roll
    back before returning the connection to the pool, so a later request can
    never inherit the previous request's tenant context.
    """
    try:
        conn = _get_pool().getconn()
    except pool.PoolError as exc:
        raise RuntimeError("VendorEdge database connection pool is temporarily exhausted.") from exc

    discard = False
    try:
        # Ensure a clean transaction state before applying a new tenant context.
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.current_org_id', %s, true)", (str(organisation_id),))
        yield conn
        conn.commit()
    except (OperationalError, InterfaceError):
        discard = True
        if not conn.closed:
            conn.rollback()
        raise
    except Exception:
        if not conn.closed:
            conn.rollback()
        raise
    finally:
        # Roll back any remaining transaction state and clear transaction-local
        # tenant state before reuse. Broken connections are discarded rather
        # than poisoning the pool for the next request.
        if not conn.closed:
            conn.rollback()
        _get_pool().putconn(conn, close=discard or bool(conn.closed))


def close_pool() -> None:
    """Close all pooled connections during graceful application shutdown."""
    global _POOL
    with _POOL_LOCK:
        if _POOL is not None:
            _POOL.closeall()
            _POOL = None
