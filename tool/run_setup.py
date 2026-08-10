"""
tool/run_setup.py
PyInstaller 진입점용 thin launcher — src.setup 패키지를 절대 임포트로 실행.

직접 실행도 가능:
    cd D:\\git.whlee2\\Rader
    .venv\\Scripts\\python tool\\run_setup.py
"""

import sys
from pathlib import Path

# 프로젝트 루트(이 파일의 부모 디렉터리)를 sys.path 맨 앞에 추가
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.setup.main import main  # noqa: E402

if __name__ == "__main__":
    main()
