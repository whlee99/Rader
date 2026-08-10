#!/usr/bin/env python3
"""
tool/build_setup.py
src/setup → PyInstaller one-dir 빌드 스크립트 (Windows 11)

사용법 (프로젝트 루트에서):
    .venv\\Scripts\\python tool\\build_setup.py

결과물:
    dist\\setup_win\\setup\\setup.exe
"""

import subprocess
import sys
import platform
from pathlib import Path


# ── 경로 ──────────────────────────────────────────────────────────────────────
ROOT      = Path(__file__).resolve().parent.parent        # D:\\git.whlee2\\Rader
TOOL_DIR  = ROOT / "tool"
ENTRY     = TOOL_DIR / "run_setup.py"                     # thin launcher
DIST_DIR  = ROOT / "dist"
BUILD_DIR = ROOT / "build"
SPEC_DIR  = ROOT / "build"

APP_NAME  = "setup"
DIST_OUT  = DIST_DIR / "setup_win"


# ── 의존 패키지 hidden-import 목록 ────────────────────────────────────────────
HIDDEN_IMPORTS = [
    "src.setup.main",
    "src.setup.model.config_model",
    "src.setup.viewmodel.setup_viewmodel",
    "src.setup.view.setup_window",
]


def check_pyinstaller():
    """PyInstaller 설치 여부 확인, 없으면 자동 설치."""
    try:
        import PyInstaller  # noqa: F401
        print(f"[OK] PyInstaller {PyInstaller.__version__}")
    except ImportError:
        print("[INFO] PyInstaller 미설치 → pip install pyinstaller")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])


def build():
    if not ENTRY.exists():
        print(f"[ERROR] 진입점 파일 없음: {ENTRY}")
        sys.exit(1)

    check_pyinstaller()

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onedir",                                  # one-dir 모드
        "--windowed",                                # 콘솔 창 숨김 (GUI 앱)
        "--name", APP_NAME,
        "--distpath", str(DIST_OUT),
        "--workpath", str(BUILD_DIR / "setup_win"),
        "--specpath", str(SPEC_DIR),
        "--noconfirm",                               # dist 덮어쓰기 확인 생략
        "--paths", str(ROOT),                        # 프로젝트 루트를 sys.path에 추가
        "--collect-all", "PySide6",                  # Qt 플러그인/리소스 전체 포함
    ]

    for imp in HIDDEN_IMPORTS:
        cmd += ["--hidden-import", imp]

    cmd.append(str(ENTRY))

    # ── 빌드 실행 ─────────────────────────────────────────────────────────────
    print(f"\n[BUILD] 플랫폼 : {platform.system()} {platform.machine()}")
    print(f"[BUILD] 출력   : {DIST_OUT / APP_NAME}")
    print(f"[BUILD] 진입점 : {ENTRY}\n")

    result = subprocess.run(cmd, cwd=str(ROOT))

    if result.returncode == 0:
        exe = DIST_OUT / APP_NAME / f"{APP_NAME}.exe"
        print(f"\n[SUCCESS] 빌드 완료:")
        print(f"  {exe}")
    else:
        print(f"\n[FAIL] PyInstaller 오류 (returncode={result.returncode})")
        sys.exit(result.returncode)


if __name__ == "__main__":
    build()
