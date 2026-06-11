#!/usr/bin/env python3
"""
tool/build_emul.py
edge_emulator.py → PyInstaller one-dir EXE 빌드 스크립트

사용법 (프로젝트 루트에서):
    .venv\Scripts\python tool\build_emul.py

결과물:
    dist\edge_emulator\edge_emulator.exe
"""

import subprocess
import sys
import shutil
from pathlib import Path


# ── 경로 설정 ─────────────────────────────────────────────────────────────────
ROOT      = Path(__file__).resolve().parent.parent   # D:\git.whlee2\Rader
TOOL_DIR  = ROOT / "tool"
SRC_ENTRY = TOOL_DIR / "edge_emulator.py"
DIST_DIR  = ROOT / "dist"
BUILD_DIR = ROOT / "build"
SPEC_DIR  = ROOT / "build"


def check_pyinstaller():
    """PyInstaller 설치 여부 확인, 없으면 설치"""
    try:
        import PyInstaller  # noqa: F401
        print(f"[OK] PyInstaller {PyInstaller.__version__} 확인")
    except ImportError:
        print("[INFO] PyInstaller 미설치 → pip install pyinstaller")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])


def build():
    check_pyinstaller()

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onedir",                          # one-dir 모드
        "--windowed",                        # 콘솔 창 없음 (GUI 앱)
        "--name", "edge_emulator",
        "--distpath", str(DIST_DIR),
        "--workpath", str(BUILD_DIR),
        "--specpath", str(SPEC_DIR),
        "--noconfirm",                       # dist 폴더 덮어쓰기 확인 생략
        # PySide6 Qt 플러그인 포함
        "--collect-all", "PySide6",
        # paho-mqtt
        "--hidden-import", "paho.mqtt.client",
        "--hidden-import", "paho.mqtt",
        str(SRC_ENTRY),
    ]

    print("\n[BUILD] PyInstaller 실행 중...\n")
    print("  " + " ".join(cmd) + "\n")

    result = subprocess.run(cmd, cwd=str(ROOT))

    if result.returncode == 0:
        exe = DIST_DIR / "edge_emulator" / "edge_emulator.exe"
        print(f"\n[SUCCESS] 빌드 완료:")
        print(f"  {exe}")
    else:
        print(f"\n[FAIL] PyInstaller 오류 (returncode={result.returncode})")
        sys.exit(result.returncode)


if __name__ == "__main__":
    build()
