"""Save complete UTF-8 test output without shell quoting or truncation."""
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from android_agent import __version__
with (ROOT/f"artifacts/python-v{__version__}-final.txt").open("w",encoding="utf-8") as stream:
    suite=unittest.defaultTestLoader.discover(str(ROOT/"tests"),pattern="test_*.py",top_level_dir=str(ROOT))
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
print(f"Tests={result.testsRun}; skipped={len(result.skipped)}; success={result.wasSuccessful()}")
sys.exit(not result.wasSuccessful())
