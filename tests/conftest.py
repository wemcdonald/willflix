import sys
from pathlib import Path

# Allow `from bin.willflix_remediate import ...` in tests
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
