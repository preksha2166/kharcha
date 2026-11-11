"""Tests always run in MOCK mode with AI off and a throwaway database."""

import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="kharcha-test-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_tmp / 'test.db').as_posix()}"
os.environ["PAYPAL_CLIENT_ID"] = ""
os.environ["PAYPAL_CLIENT_SECRET"] = ""
os.environ["GEMINI_API_KEY"] = ""
os.environ["DEMO_MODE"] = "true"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
