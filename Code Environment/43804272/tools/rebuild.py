from pathlib import Path
import subprocess, sys
root = Path(__file__).resolve().parents[3]
raise SystemExit(subprocess.call([sys.executable, str(root / 'Code' / 'build_rq4_code_environments.py'), '--project-id', '43804272', '--replace'], cwd=root))
