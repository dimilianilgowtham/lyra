"""Run backend tests against a temporary database, leaving saved user data intact."""

import os
import secrets
from pathlib import Path
import sys
import tempfile
import unittest


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    backend_dir = Path(__file__).resolve().parent.parent / "lyra-backend"
    sys.path.insert(0, str(backend_dir))
    with tempfile.TemporaryDirectory(prefix="lyra-tests-") as test_dir:
        os.environ["DATABASE_PATH"] = str(Path(test_dir) / "lyra.db")
        os.environ["BACKEND_AUTH_TOKEN"] = secrets.token_urlsafe(32)
        suite = unittest.defaultTestLoader.discover(str(backend_dir / "tests"), pattern="test_*.py")
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        sys.exit(0 if result.wasSuccessful() else 1)
