#!/usr/bin/env python3
"""
tool/build_monitor.py
src/monitor → PyInstaller one-dir 빌드 스크립트

──────────────────────────────────────────────────────────────
플랫폼별 실행 방법 (프로젝트 루트에서):

  Windows 11:
      .venv\\Scripts\\python tool\\build_monitor.py

  RPi4 Ubuntu 22.04:
      .venv/bin/python3 tool/build_monitor.py

PyInstaller 는 크로스 컴파일을 지원하지 않으므로
각 플랫폼에서 직접 실행해야 합니다.
──────────────────────────────────────────────────────────────

결과물:
  dist/monitor_win/monitor/monitor.exe   (Windows 11)
  dist/monitor_linux/monitor/monitor     (RPi4 Ubuntu 22.04)
"""

import subprocess
import sys
import platform
from pathlib import Path


# ── 경로 ──────────────────────────────────────────────────────────────────────
ROOT      = Path(__file__).resolve().parent.parent        # D:\\git.whlee2\\Rader
TOOL_DIR  = ROOT / "tool"
ENTRY     = TOOL_DIR / "run_monitor.py"                   # thin launcher
DIST_DIR  = ROOT / "dist"
BUILD_DIR = ROOT / "build"
SPEC_DIR  = ROOT / "build"

IS_WINDOWS = sys.platform == "win32"
PLAT_TAG   = "win" if IS_WINDOWS else "linux"
APP_NAME   = "monitor"
DIST_OUT   = DIST_DIR / f"monitor_{PLAT_TAG}"


# ── 의존 패키지 hidden-import 목록 ────────────────────────────────────────────
HIDDEN_IMPORTS = [
    "paho.mqtt",
    "paho.mqtt.client",
    "src.monitor.model.mqtt_model",
    "src.monitor.viewmodel.monitor_viewmodel",
    "src.monitor.view.dashboard",
    "src.monitor.view.widgets",
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
        "--name", APP_NAME,
        "--distpath", str(DIST_OUT),
        "--workpath", str(BUILD_DIR / f"monitor_{PLAT_TAG}"),
        "--specpath", str(SPEC_DIR),
        "--noconfirm",                               # dist 덮어쓰기 확인 생략
        "--paths", str(ROOT),                        # 프로젝트 루트를 sys.path에 추가
        "--collect-all", "PySide6",                  # Qt 플러그인/리소스 전체 포함
        "--collect-all", "shiboken6",               # shiboken6/libshiboken DLL 포함
    ]

    for imp in HIDDEN_IMPORTS:
        cmd += ["--hidden-import", imp]

    if IS_WINDOWS:
        cmd.append("--windowed")                     # Win: 콘솔 창 숨김

    cmd.append(str(ENTRY))

    # ── 빌드 실행 ─────────────────────────────────────────────────────────────
    print(f"\n[BUILD] 플랫폼 : {platform.system()} {platform.machine()}")
    print(f"[BUILD] 출력   : {DIST_OUT / APP_NAME}")
    print(f"[BUILD] 진입점 : {ENTRY}\n")

    result = subprocess.run(cmd, cwd=str(ROOT))

    if result.returncode != 0:
        print(f"\n[FAIL] PyInstaller 오류 (returncode={result.returncode})")
        sys.exit(result.returncode)

    exe_name = f"{APP_NAME}.exe" if IS_WINDOWS else APP_NAME
    exe_path = DIST_OUT / APP_NAME / exe_name
    print(f"\n[SUCCESS] 빌드 완료:")
    print(f"  {exe_path}")

    if IS_WINDOWS:
        print("\n  RPi4(Ubuntu 22.04) 빌드는 해당 장비에서 동일 스크립트를 실행하세요.")
        print("  git pull 후: .venv/bin/python3 tool/build_monitor.py")
    else:
        print("\n  Windows 빌드는 Win11 환경에서 동일 스크립트를 실행하세요.")
        print("  .venv\\Scripts\\python tool\\build_monitor.py")


if __name__ == "__main__":
    build()
