#!/usr/bin/env python3
"""
tool/build_all.py
setup + monitor + RaderFlash + edge_emulator → dist/Rader/ (공유 폴더)

4개 앱을 단일 PyInstaller 빌드로 묶어 PySide6/shiboken6/esptool DLL 을 공유.
개별 빌드 대비 디스크 용량 대폭 절감 및 배포 단순화.

사용법 (프로젝트 루트에서):
    .venv\\Scripts\\python tool\\build_all.py

결과물:
    dist\\Rader\\
        setup.exe
        monitor.exe
        RaderFlash.exe
        edge_emulator.exe
        _internal\\          ← PySide6, shiboken6, esptool 공유 DLL
"""

import subprocess
import sys
import platform
from pathlib import Path


# ── 경로 ──────────────────────────────────────────────────────────────────────
ROOT      = Path(__file__).resolve().parent.parent   # D:\\git.whlee2\\Rader
BUILD_DIR = ROOT / "build"
DIST_DIR  = ROOT / "dist"
SPEC_FILE = BUILD_DIR / "Rader_all.spec"


# ── Spec 파일 내용 (PyInstaller 6.x 호환) ─────────────────────────────────────
# SPECPATH 는 PyInstaller 가 spec 실행 시 자동으로 주입하는 변수.
# spec 이 build/ 에 위치하므로 ROOT = os.path.dirname(SPECPATH).
SPEC_CONTENT = r"""# Rader_all.spec  (자동 생성 by build_all.py)
# 4개 앱 공유 빌드: setup / monitor / RaderFlash / edge_emulator
import os
from PyInstaller.utils.hooks import collect_all

ROOT = os.path.dirname(SPECPATH)   # .../Rader/build → .../Rader

# ── 공유 패키지 수집 ──────────────────────────────────────────────────────────
def _col(*pkgs):
    d, b, h = [], [], []
    for p in pkgs:
        td, tb, th = collect_all(p)
        d += td; b += tb; h += th
    return d, b, h

qt_datas,    qt_bins,    qt_hidden    = _col('PySide6', 'shiboken6')
esptool_datas, esptool_bins, esptool_hidden = _col('esptool', 'rich_click', 'rich')

# ── Analysis ──────────────────────────────────────────────────────────────────
a_setup = Analysis(
    [os.path.join(ROOT, 'tool', 'run_setup.py')],
    pathex=[ROOT],
    binaries=qt_bins,
    datas=qt_datas,
    hiddenimports=qt_hidden + [
        'src.setup.main',
        'src.setup.model.config_model',
        'src.setup.viewmodel.setup_viewmodel',
        'src.setup.view.setup_window',
    ],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=[], noarchive=False,
)

a_monitor = Analysis(
    [os.path.join(ROOT, 'tool', 'run_monitor.py')],
    pathex=[ROOT],
    binaries=qt_bins,
    datas=qt_datas,
    hiddenimports=qt_hidden + [
        'paho.mqtt', 'paho.mqtt.client',
        'src.monitor.model.mqtt_model',
        'src.monitor.viewmodel.monitor_viewmodel',
        'src.monitor.view.dashboard',
        'src.monitor.view.widgets',
    ],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=[], noarchive=False,
)

a_flash = Analysis(
    [os.path.join(ROOT, 'tool', 'flash_esp32.py')],
    pathex=[ROOT],
    binaries=qt_bins + esptool_bins,
    datas=qt_datas + esptool_datas,
    hiddenimports=qt_hidden + esptool_hidden,
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=[], noarchive=False,
)

a_emul = Analysis(
    [os.path.join(ROOT, 'tool', 'edge_emulator.py')],
    pathex=[ROOT],
    binaries=qt_bins,
    datas=qt_datas,
    hiddenimports=qt_hidden + [
        'paho.mqtt', 'paho.mqtt.client',
    ],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=[], noarchive=False,
)

# ── PYZ ───────────────────────────────────────────────────────────────────────
pyz_setup   = PYZ(a_setup.pure)
pyz_monitor = PYZ(a_monitor.pure)
pyz_flash   = PYZ(a_flash.pure)
pyz_emul    = PYZ(a_emul.pure)

# ── EXE ───────────────────────────────────────────────────────────────────────
_kw = dict(
    debug=False, bootloader_ignore_signals=False,
    strip=False, upx=True, upx_exclude=[], console=False,
    disable_windowed_traceback=False, argv_emulation=False,
    target_arch=None, codesign_identity=None, entitlements_file=None,
)

exe_setup   = EXE(pyz_setup,   a_setup.scripts,   [], name='setup',         **_kw)
exe_monitor = EXE(pyz_monitor, a_monitor.scripts, [], name='monitor',       **_kw)
exe_flash   = EXE(pyz_flash,   a_flash.scripts,   [], name='RaderFlash',    **_kw)
exe_emul    = EXE(pyz_emul,    a_emul.scripts,    [], name='edge_emulator', **_kw)

# ── COLLECT (단일 공유 폴더: dist/Rader/) ─────────────────────────────────────
# COLLECT 은 동일 경로의 파일을 자동 중복 제거하므로
# PySide6/shiboken6 DLL 은 한 번만 포함됨.
coll = COLLECT(
    exe_setup,   a_setup.binaries,   a_setup.datas,
    exe_monitor, a_monitor.binaries, a_monitor.datas,
    exe_flash,   a_flash.binaries,   a_flash.datas,
    exe_emul,    a_emul.binaries,    a_emul.datas,
    strip=False, upx=True, upx_exclude=[],
    name='Rader',
)
"""


def check_pyinstaller():
    try:
        import PyInstaller  # noqa: F401
        print(f"[OK] PyInstaller {PyInstaller.__version__}")
    except ImportError:
        print("[INFO] PyInstaller 미설치 → pip install pyinstaller")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])


def build():
    check_pyinstaller()

    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    SPEC_FILE.write_text(SPEC_CONTENT, encoding="utf-8")
    print(f"[INFO] spec 생성: {SPEC_FILE}")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--distpath", str(DIST_DIR),
        "--workpath", str(BUILD_DIR / "Rader_all"),
        "--noconfirm",
        str(SPEC_FILE),
    ]

    print(f"\n[BUILD] 플랫폼 : {platform.system()} {platform.machine()}")
    print(f"[BUILD] 출력   : {DIST_DIR / 'Rader'}")
    print(f"[BUILD] 앱     : setup / monitor / RaderFlash / edge_emulator\n")

    result = subprocess.run(cmd, cwd=str(ROOT))

    if result.returncode == 0:
        out = DIST_DIR / "Rader"
        print(f"\n[SUCCESS] 빌드 완료: {out}")
        for exe in sorted(out.glob("*.exe")):
            size = exe.stat().st_size / 1024
            print(f"  {exe.name:30s}  {size:7.0f} KB")
        internal = out / "_internal"
        if internal.exists():
            total = sum(f.stat().st_size for f in internal.rglob("*") if f.is_file())
            print(f"  {'_internal/ (공유 DLL)':30s}  {total/1024/1024:7.1f} MB")
    else:
        print(f"\n[FAIL] PyInstaller 오류 (returncode={result.returncode})")
        sys.exit(result.returncode)


if __name__ == "__main__":
    build()
