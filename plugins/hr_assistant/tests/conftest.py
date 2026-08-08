"""hr_assistant plugin conftest — 把项目根加到 sys.path 让 `import CorpAI` 找到。"""
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
