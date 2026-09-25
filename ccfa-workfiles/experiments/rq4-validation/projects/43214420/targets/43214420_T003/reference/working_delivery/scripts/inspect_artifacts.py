from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from artifact_runtime import parse_artifacts

print(json.dumps(parse_artifacts(ROOT / "dist"), ensure_ascii=False, indent=2))
