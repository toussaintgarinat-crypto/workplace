import sys
from pathlib import Path

_BRIQUE = Path(__file__).parent
if str(_BRIQUE) not in sys.path:
    sys.path.insert(0, str(_BRIQUE))
