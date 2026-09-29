# The package lives under src/ and is not installed (no pip install, on principle): it is made importable
# here, so `python -m unittest` runs from the repository root, on Windows as elsewhere.
import sys
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1] / "src")
)
