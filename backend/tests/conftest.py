"""Loaded by pytest before the test modules.

Tests always run on their own temporary database: BI_DATABASE_URL (which may point at production) is
ignored. To run the suite on PostgreSQL, give an empty, disposable database in BI_TEST_DATABASE_URL.
"""
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="bi_test_")
os.environ["BI_DATA_DIR"] = _tmp
os.environ["BI_DATABASE_URL"] = os.environ.get("BI_TEST_DATABASE_URL") or f"sqlite:///{_tmp}/test.db"
os.environ["BI_BACKUP_DAILY_AT"] = ""
os.environ["BI_ALLOWED_HOSTS"] = "testserver"  # host name used by the in-process test client
os.environ["BI_MODE"] = "demo"  # most tests use the fictional dataset; production behaviour: test_production.py
