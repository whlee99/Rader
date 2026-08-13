"""
build_Flash.py
flash_esp32.py → dist/RaderFlash.exe 빌드 스크립트

사용법:
    python build_Flash.py
"""

import subprocess
import sys
import os
import shutil

SCRIPT  = "flash_esp32.py"
NAME    = "RaderFlash"
HERE    = os.path.dirname(os.path.abspath(__file__))
DIST    = os.path.join(HERE, "dist")
BUILD   = os.path.join(HERE, "build")
SPEC    = os.path.join(HERE, f"{NAME}.spec")

def main():
    os.chdir(HERE)

    # ── PyInstaller 설치 확인 ──────────────────────────────────────────
    try:
        import PyInstaller
    except ImportError:
        print("[BUILD] PyInstaller 미설치 → pip install pyinstaller")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # ── 이전 빌드 정리 ────────────────────────────────────────────────
    for path in [SPEC, os.path.join(DIST, NAME + ".exe")]:
        if os.path.exists(path):
            os.remove(path)
            print(f"[BUILD] 삭제: {path}")

    # ── PyInstaller 실행 ─────────────────────────────────────────────
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",
        "--name", NAME,
        "--distpath", DIST,
        "--workpath", BUILD,
        "--specpath", HERE,
        "--collect-all", "PySide6",
        "--collect-all", "shiboken6",
        "--collect-all", "esptool",
        "--collect-all", "rich_click",
        "--collect-all", "rich",
        SCRIPT,
    ]

    print("[BUILD] 명령:", " ".join(cmd))
    print("[BUILD] 빌드 시작...\n")

    result = subprocess.run(cmd)

    if result.returncode != 0:
        print("\n[BUILD] ❌ 빌드 실패")
        sys.exit(result.returncode)

    exe = os.path.join(DIST, NAME + ".exe")
    if os.path.exists(exe):
        size_mb = os.path.getsize(exe) / 1024 / 1024
        print(f"\n[BUILD] ✅ 완료: {exe}  ({size_mb:.1f} MB)")
    else:
        print("\n[BUILD] ❌ exe 파일을 찾을 수 없음")
        sys.exit(1)

if __name__ == "__main__":
    main()
