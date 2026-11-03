"""Serialize publishers before taking a repeatable input snapshot."""
from contextlib import contextmanager
from psycopg.pq import TransactionStatus


@contextmanager
def snapshot_lock(conn,key):
    # Session locking precedes BEGIN: a waiting repeatable-read transaction must
    # not freeze its snapshot before the preceding publisher commits.
    if conn.autocommit and conn.info.transaction_status==TransactionStatus.IDLE:
        conn.execute('SELECT pg_advisory_lock(hashtextextended(%s,0))',(key,))
        try:
            with conn.transaction():
                conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
                yield
        finally:
            if not conn.closed:conn.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))',(key,))
    else:
        # Respect an enclosing transaction's isolation and ownership.
        with conn.transaction():
            conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(key,))
            yield
