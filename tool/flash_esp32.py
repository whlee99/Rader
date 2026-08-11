"""
Rader ESP32 Flash Tool
- PySide6 GUI
- Tab 1: Flash (COM port auto-detect, esptool merged.bin)
- Tab 2: Serial Monitor (115200, send/receive)
- Build exe: pyinstaller --onefile --windowed --name RaderFlash flash_esp32.py
"""

import sys
import os
import glob
import threading
import subprocess
import serial
import serial.tools.list_ports

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QPushButton, QFileDialog, QTextEdit,
    QProgressBar, QGroupBox, QSizePolicy, QTabWidget, QLineEdit,
    QCheckBox, QSplitter
)
from PySide6.QtCore import Qt, Signal, QObject, QTimer
from PySide6.QtGui import QFont, QColor, QTextCursor

# ── esptool 위치 탐색 ───────────────────────────────────────────────────────
def find_esptool():
    """Find esptool command. Works both as .py script and frozen exe.

    PyInstaller --onefile exe 에서 sys.executable 은 RaderFlash.exe 자신이므로
    [sys.executable, "-m", "esptool"] 을 그대로 사용하면 exe가 자신을 재실행함.
    → frozen 여부를 확인하고 실제 Python 경로를 우선 탐색한다.
    """
    import shutil

    is_frozen = getattr(sys, "_MEIPASS", None) is not None

    # ── PlatformIO 번들 경로 (프로젝트 전용, 가장 안정적) ──────────────────
    pio_python  = os.path.expanduser(
        r"~\.platformio\penv\Scripts\python.exe")
    pio_esptool = os.path.expanduser(
        r"~\.platformio\packages\tool-esptoolpy\esptool.py")
    if os.path.exists(pio_python) and os.path.exists(pio_esptool):
        return [pio_python, pio_esptool]

    # ── PATH 에 esptool 실행 파일이 있으면 직접 사용 ──────────────────────
    for name in ("esptool", "esptool.exe"):
        found = shutil.which(name)
        if found:
            return [found]

    # ── 스크립트로 직접 실행 시에만 sys.executable 사용 ───────────────────
    if not is_frozen:
        try:
            import esptool  # noqa: F401
            return [sys.executable, "-m", "esptool"]
        except ImportError:
            pass
        if os.path.exists(pio_esptool):
            return [sys.executable, pio_esptool]

    # ── 시스템 Python 탐색 (frozen 환경 fallback) ─────────────────────────
    for py in ("python", "python3", "python.exe"):
        found = shutil.which(py)
        if found and found != sys.executable:
            try:
                r = subprocess.run(
                    [found, "-c", "import esptool"],
                    capture_output=True, timeout=5)
                if r.returncode == 0:
                    return [found, "-m", "esptool"]
            except Exception:
                pass

    return None

ESPTOOL_CMD = find_esptool()

# ── 기본 fw 폴더 ────────────────────────────────────────────────────────────
def default_fw_dir():
    here = os.path.dirname(os.path.abspath(__file__))
    # tool/ → RaderESP/fw/
    candidate = os.path.normpath(os.path.join(here, "..", "esp", "RaderESP", "fw"))
    if os.path.isdir(candidate):
        return candidate
    return here

# ── 신호 클래스 ────────────────────────────────────────────────────────────
class FlashSignals(QObject):
    log      = Signal(str)
    progress = Signal(int)         # 0~100, -1=indeterminate
    done     = Signal(bool)        # True=success

class MonitorSignals(QObject):
    data   = Signal(str)   # \n 포함 완성 라인
    prompt = Signal(str)   # \n 없는 프롬프트 라인 (RADER> 등)
    status = Signal(str)

# ── PuTTY 스타일 터미널 위젯 ────────────────────────────────────────────────
MAX_LINES = 5000   # 이 줄 수 초과 시 자동 clear

class TerminalWidget(QTextEdit):
    """직접 입력 가능한 터미널 위젯 (PuTTY 스타일).
    수신 데이터는 흰색, 입력 중 글자는 연두색으로 표시된다.
    Enter → send_line Signal 발신 / Ctrl+C → send_bytes Signal 발신.
    """
    send_line  = Signal(str)   # 한 줄 입력 완료
    send_bytes = Signal(bytes) # raw 바이트 전송 (Ctrl+C 등)

    COLOR_RX    = "#d4d4d4"   # 수신 텍스트
    COLOR_INPUT = "#90ee90"   # 입력 중 텍스트
    COLOR_TS    = "#888888"   # 타임스탬프
    COLOR_ECHO  = "#569cd6"   # 전송 echo

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(False)
        self.setUndoRedoEnabled(False)
        self.setFont(QFont("Consolas", 9))
        self.setStyleSheet("background:#1e1e1e; color:#d4d4d4;")
        self._buf = ""           # 현재 입력 중인 라인 버퍼
        self._timestamp = False

    # ── 공개 API ──────────────────────────────────────────────────────
    def set_timestamp(self, on: bool):
        self._timestamp = on

    def _check_and_trim(self):
        """MAX_LINES 초과 시 전체 clear 후 경고 메시지 삽입."""
        doc = self.document()
        if doc.blockCount() > MAX_LINES:
            self.clear()
            self._buf = ""
            c = self.textCursor()
            fmt = self.currentCharFormat()
            fmt.setForeground(QColor("#ffaa00"))
            c.insertText("-- [자동 초기화: %d 줄 초과] --\n" % MAX_LINES, fmt)
            self.setTextCursor(c)

    def append_rx(self, text: str):
        """수신 데이터를 터미널에 추가. 입력 버퍼를 보호한다."""
        self._check_and_trim()

        c = self.textCursor()
        c.movePosition(QTextCursor.End)

        # 입력 중인 버퍼가 있으면 일단 지운다
        if self._buf:
            c.movePosition(QTextCursor.End)
            for _ in range(len(self._buf)):
                c.deletePreviousChar()
            self.setTextCursor(c)
            c = self.textCursor()

        # 현재 줄이 비어있지 않으면 (프롬프트 뒤 등) 먼저 줄바꿈
        if not c.atBlockStart():
            fmt = self.currentCharFormat()
            fmt.setForeground(QColor(self.COLOR_RX))
            c.insertText("\n", fmt)
            self.setTextCursor(c)
            c = self.textCursor()

        # 수신 텍스트 삽입
        if self._timestamp:
            import datetime
            ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:12]
            fmt = self.currentCharFormat()
            fmt.setForeground(QColor(self.COLOR_TS))
            c.insertText("[%s] " % ts, fmt)
            c = self.textCursor()

        fmt = self.currentCharFormat()
        fmt.setForeground(QColor(self.COLOR_RX))
        c.insertText(text + "\n", fmt)
        self.setTextCursor(c)

        # 입력 버퍼 다시 표시
        if self._buf:
            fmt = self.currentCharFormat()
            fmt.setForeground(QColor(self.COLOR_INPUT))
            c = self.textCursor()
            c.insertText(self._buf, fmt)
            self.setTextCursor(c)

        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())

    def append_prompt(self, text: str):
        """프롬프트 라인 표시 - \n 없음, 커서가 프롬프트 바로 뒤에 위치."""
        self._check_and_trim()
        c = self.textCursor()
        c.movePosition(QTextCursor.End)

        # 입력 중인 버퍼 지우기
        if self._buf:
            for _ in range(len(self._buf)):
                c.deletePreviousChar()
            self.setTextCursor(c)
            c = self.textCursor()

        # 현재 줄이 비어있지 않으면 줄바꿈
        if not c.atBlockStart():
            fmt = self.currentCharFormat()
            fmt.setForeground(QColor(self.COLOR_RX))
            c.insertText("\n", fmt)
            self.setTextCursor(c)
            c = self.textCursor()

        fmt = self.currentCharFormat()
        fmt.setForeground(QColor(self.COLOR_RX))
        c.insertText(text, fmt)   # ← \n 없음: 커서가 프롬프트 뒤에 위치
        self.setTextCursor(c)

        # 입력 버퍼 다시 표시
        if self._buf:
            fmt = self.currentCharFormat()
            fmt.setForeground(QColor(self.COLOR_INPUT))
            c = self.textCursor()
            c.insertText(self._buf, fmt)
            self.setTextCursor(c)

        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())

    def append_status(self, text: str, color="#ffaa00"):
        c = self.textCursor()
        c.movePosition(QTextCursor.End)
        fmt = self.currentCharFormat()
        fmt.setForeground(QColor(color))
        c.insertText("-- %s --\n" % text, fmt)
        self.setTextCursor(c)
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())

    # ── 키 이벤트 ─────────────────────────────────────────────────────
    def keyPressEvent(self, event):
        key  = event.key()
        mods = event.modifiers()

        # 항상 커서를 맨 끝으로
        c = self.textCursor()
        c.movePosition(QTextCursor.End)
        self.setTextCursor(c)

        # Ctrl+C → 인터럽트
        if key == Qt.Key_C and mods == Qt.ControlModifier:
            self.send_bytes.emit(b"\x03")
            return

        # Ctrl+L → 화면 지우기
        if key == Qt.Key_L and mods == Qt.ControlModifier:
            self.clear()
            self._buf = ""
            return

        # Enter → 전송
        if key in (Qt.Key_Return, Qt.Key_Enter):
            line = self._buf
            if line:
                # 입력 내용이 있을 때만 줄바꿈 (빈 Enter는 빈 줄 생성 안 함)
                c = self.textCursor()
                fmt = self.currentCharFormat()
                fmt.setForeground(QColor(self.COLOR_ECHO))
                c.insertText("\n", fmt)
                self.setTextCursor(c)
            self._buf = ""
            self.send_line.emit(line)
            self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())
            return

        # Backspace
        if key == Qt.Key_Backspace:
            if self._buf:
                self._buf = self._buf[:-1]
                c = self.textCursor()
                c.deletePreviousChar()
                self.setTextCursor(c)
            return

        # Ctrl+V paste
        if key == Qt.Key_V and mods == Qt.ControlModifier:
            clip = QApplication.clipboard().text()
            if clip:
                self._insert_input(clip)
            return

        # 일반 출력 가능 문자
        ch = event.text()
        if ch and ch.isprintable():
            self._insert_input(ch)

    def _insert_input(self, text: str):
        self._buf += text
        c = self.textCursor()
        fmt = self.currentCharFormat()
        fmt.setForeground(QColor(self.COLOR_INPUT))
        c.insertText(text, fmt)
        self.setTextCursor(c)

    # 마우스 클릭으로 커서가 이동해도 다음 키 입력 시 끝으로 돌아오므로 허용

# ── Serial Monitor 백엔드 ──────────────────────────────────────────────────
class SerialMonitor:
    def __init__(self, signals: MonitorSignals):
        self.signals = signals
        self._serial = None
        self._thread = None
        self._running = False

    def connect(self, port, baud):
        if self._running:
            return
        try:
            self._serial = serial.Serial(port, baud, timeout=0.1)
            self._running = True
            self._thread = threading.Thread(target=self._read_loop, daemon=True)
            self._thread.start()
            self.signals.status.emit("Connected: %s @ %d" % (port, baud))
        except Exception as e:
            self.signals.status.emit("ERROR: " + str(e))

    def disconnect(self):
        self._running = False
        if self._serial and self._serial.is_open:
            self._serial.close()
        self._serial = None
        self.signals.status.emit("Disconnected")

    def send(self, text):
        if self._serial and self._serial.is_open:
            try:
                self._serial.write((text + "\r\n").encode("utf-8", errors="replace"))
            except Exception as e:
                self.signals.status.emit("Send error: " + str(e))

    def _read_loop(self):
        import time
        buf = b""
        last_rx = time.monotonic()
        PROMPT_TIMEOUT = 0.06  # 60ms: \n 없는 프롬프트(RADER>) 강제 플러시
        while self._running:
            try:
                data = self._serial.read(256)
                if data:
                    buf += data
                    last_rx = time.monotonic()
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        text = line.decode("utf-8", errors="replace").rstrip("\r")
                        if text:           # CR/LF 아티팩트(빈 줄) 필터링
                            self.signals.data.emit(text)
                elif buf and (time.monotonic() - last_rx) > PROMPT_TIMEOUT:
                    # \n 없이 끝나는 프롬프트 라인 (예: "RADER> ") 강제 출력
                    text = buf.decode("utf-8", errors="replace").rstrip("\r")
                    buf = b""
                    if text:
                        self.signals.prompt.emit(text)  # ← prompt 신호
            except Exception:
                break
        self._running = False
        self.signals.status.emit("Disconnected")

# ── 메인 윈도우 ────────────────────────────────────────────────────────────
class FlashTool(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Rader ESP32 Flash Tool")
        self.setMinimumWidth(720)
        self.setMinimumHeight(600)
        self.signals = FlashSignals()
        self.signals.log.connect(self._append_log)
        self.signals.progress.connect(self._set_progress)
        self.signals.done.connect(self._flash_done)

        self.mon_signals = MonitorSignals()
        self.mon_signals.data.connect(self._mon_append)
        self.mon_signals.prompt.connect(self._mon_append_prompt)
        self.mon_signals.status.connect(self._mon_status)
        self._last_sent = ""   # echo 억제용
        self.monitor = SerialMonitor(self.mon_signals)

        self._build_ui()
        self._refresh_ports()
        self._refresh_fw_list()

    # ── UI 구성 ───────────────────────────────────────────────────────────
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)

        # 공통 포트 선택
        pg = QGroupBox("Serial Port")
        pl = QHBoxLayout(pg)
        self.combo_port = QComboBox()
        self.combo_port.setMinimumWidth(200)
        btn_refresh = QPushButton("Refresh")
        btn_refresh.setFixedWidth(80)
        btn_refresh.clicked.connect(self._refresh_ports)
        pl.addWidget(QLabel("Port:"))
        pl.addWidget(self.combo_port)
        pl.addWidget(btn_refresh)
        pl.addStretch()
        root.addWidget(pg)

        # 탭
        tabs = QTabWidget()
        tabs.addTab(self._build_flash_tab(), "⚡  Flash")
        tabs.addTab(self._build_monitor_tab(), "🖥  Serial Monitor")
        root.addWidget(tabs)

    # ── Flash 탭 ─────────────────────────────────────────────────────────
    def _build_flash_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(8)

        # Firmware
        fg = QGroupBox("Firmware")
        fl = QVBoxLayout(fg)
        row1 = QHBoxLayout()
        self.combo_fw = QComboBox()
        self.combo_fw.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        btn_browse = QPushButton("Browse…")
        btn_browse.setFixedWidth(80)
        btn_browse.clicked.connect(self._browse_fw)
        row1.addWidget(QLabel("File:"))
        row1.addWidget(self.combo_fw)
        row1.addWidget(btn_browse)
        fl.addLayout(row1)
        self.lbl_fw_hint = QLabel("")
        self.lbl_fw_hint.setStyleSheet("color: gray; font-size: 11px;")
        fl.addWidget(self.lbl_fw_hint)
        layout.addWidget(fg)

        # Flash 버튼
        self.btn_flash = QPushButton("⚡  FLASH")
        self.btn_flash.setFixedHeight(44)
        self.btn_flash.setFont(QFont("Arial", 12, QFont.Bold))
        self.btn_flash.setStyleSheet(
            "QPushButton{background:#1a73e8;color:white;border-radius:6px;}"
            "QPushButton:hover{background:#1558b0;}"
            "QPushButton:disabled{background:#aaa;}")
        self.btn_flash.clicked.connect(self._start_flash)
        layout.addWidget(self.btn_flash)

        # 진행 바
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        # 로그
        self.flash_log = QTextEdit()
        self.flash_log.setReadOnly(True)
        self.flash_log.setFont(QFont("Consolas", 9))
        layout.addWidget(self.flash_log)

        # 상태
        self.lbl_status = QLabel("Ready")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        self.lbl_status.setFixedHeight(26)
        self.lbl_status.setStyleSheet("font-weight:bold;font-size:13px;")
        layout.addWidget(self.lbl_status)
        return w

    # ── Serial Monitor 탭 ─────────────────────────────────────────────────
    def _build_monitor_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(6)

        # 설정 바
        cfg = QHBoxLayout()
        self.combo_baud = QComboBox()
        for b in ["9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600"]:
            self.combo_baud.addItem(b)
        self.combo_baud.setCurrentText("115200")
        self.btn_connect = QPushButton("Connect")
        self.btn_connect.setFixedWidth(90)
        self.btn_connect.setStyleSheet(
            "QPushButton{background:#2e7d32;color:white;border-radius:4px;}"
            "QPushButton:hover{background:#1b5e20;}")
        self.btn_connect.clicked.connect(self._toggle_connect)
        self.chk_timestamp = QCheckBox("Timestamp")
        self.chk_timestamp.toggled.connect(
            lambda v: self.terminal.set_timestamp(v))
        btn_clear = QPushButton("Clear")
        btn_clear.setFixedWidth(60)
        btn_clear.clicked.connect(lambda: self.terminal.clear())
        cfg.addWidget(QLabel("Baud:"))
        cfg.addWidget(self.combo_baud)
        cfg.addWidget(self.btn_connect)
        cfg.addWidget(self.chk_timestamp)
        cfg.addStretch()
        cfg.addWidget(btn_clear)
        layout.addLayout(cfg)

        # 상태 표시
        self.lbl_mon_status = QLabel("Disconnected  |  클릭 후 바로 입력  (Enter=전송  Ctrl+C=인터럽트  Ctrl+L=화면지우기)")
        self.lbl_mon_status.setStyleSheet("color:gray;font-size:11px;")
        layout.addWidget(self.lbl_mon_status)

        # 터미널 (PuTTY 스타일)
        self.terminal = TerminalWidget()
        self.terminal.send_line.connect(self._mon_send_line)
        self.terminal.send_bytes.connect(self._mon_send_bytes)
        layout.addWidget(self.terminal)
        return w

    # ── COM 포트 갱신 ─────────────────────────────────────────────────────
    def _refresh_ports(self):
        self.combo_port.clear()
        ports = serial.tools.list_ports.comports()
        for p in sorted(ports, key=lambda x: x.device):
            self.combo_port.addItem(
                "%s  —  %s" % (p.device, p.description), userData=p.device)
        if not ports:
            self.combo_port.addItem("(No port found)", userData=None)

    # ── FW 파일 목록 갱신 ────────────────────────────────────────────────
    def _refresh_fw_list(self):
        fw_dir = default_fw_dir()
        self.combo_fw.clear()
        # merged.bin 우선, 그 다음 firmware.bin
        files = sorted(glob.glob(os.path.join(fw_dir, "merged-*.bin")), reverse=True)
        files += sorted(glob.glob(os.path.join(fw_dir, "merged.bin")))
        files += sorted(glob.glob(os.path.join(fw_dir, "firmware-*.bin")), reverse=True)
        files += sorted(glob.glob(os.path.join(fw_dir, "firmware.bin")))
        seen = set()
        for f in files:
            if f not in seen:
                seen.add(f)
                self.combo_fw.addItem(os.path.basename(f), userData=f)
        if self.combo_fw.count() == 0:
            self.combo_fw.addItem("(No firmware found)", userData=None)
        self._update_fw_hint()
        self.combo_fw.currentIndexChanged.connect(self._update_fw_hint)

    def _update_fw_hint(self):
        path = self.combo_fw.currentData()
        if path and os.path.exists(path):
            size = os.path.getsize(path)
            self.lbl_fw_hint.setText("  %s  |  %.1f KB" % (
                os.path.abspath(path), size / 1024))
        else:
            self.lbl_fw_hint.setText("")

    def _browse_fw(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Firmware", default_fw_dir(), "Binary (*.bin)")
        if path:
            self.combo_fw.insertItem(0, os.path.basename(path), userData=path)
            self.combo_fw.setCurrentIndex(0)

    # ── 플래싱 ───────────────────────────────────────────────────────────
    def _start_flash(self):
        port = self.combo_port.currentData()
        fw   = self.combo_fw.currentData()

        if not port:
            self._set_status("❌ No COM port selected", "red")
            return
        if not fw or not os.path.exists(fw):
            self._set_status("❌ No firmware file selected", "red")
            return
        if not ESPTOOL_CMD:
            self._set_status("❌ esptool not found (pip install esptool)", "red")
            return

        self.btn_flash.setEnabled(False)
        self.flash_log.clear()
        self.progress.setValue(0)
        self._set_status("Flashing…", "#1a73e8")

        # 백그라운드 스레드
        t = threading.Thread(target=self._do_flash, args=(port, fw), daemon=True)
        t.start()

    def _do_flash(self, port, fw):
        sig = self.signals
        # merged.bin → 0x0 한 번에 기록
        cmd = ESPTOOL_CMD + [
            "--chip", "esp32",
            "--port", port,
            "--baud", "921600",
            "--before", "default_reset",
            "--after",  "hard_reset",
            "write_flash",
            "--flash_mode", "dio",
            "--flash_freq", "40m",
            "--flash_size", "detect",
            "0x0", fw,
        ]
        sig.log.emit("CMD: " + " ".join(cmd))
        sig.log.emit("─" * 60)

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            percent = 0
            for line in proc.stdout:
                line = line.rstrip()
                sig.log.emit(line)
                # 진행률 파싱 "Writing at 0x... (XX %)"
                if "(" in line and "%)" in line:
                    try:
                        pct = int(line.split("(")[1].split("%")[0].strip())
                        sig.progress.emit(pct)
                        percent = pct
                    except Exception:
                        pass
            proc.wait()
            success = (proc.returncode == 0)
            sig.progress.emit(100 if success else 0)
            sig.done.emit(success)
        except Exception as e:
            sig.log.emit("ERROR: " + str(e))
            sig.done.emit(False)

    # ── UI 업데이트 콜백 ─────────────────────────────────────────────────
    def _append_log(self, text):
        if self.flash_log.document().blockCount() > MAX_LINES:
            self.flash_log.clear()
            self.flash_log.append("-- [자동 초기화: %d 줄 초과] --" % MAX_LINES)
        self.flash_log.append(text)
        self.flash_log.verticalScrollBar().setValue(
            self.flash_log.verticalScrollBar().maximum())

    def _set_progress(self, val):
        if val < 0:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, 100)
            self.progress.setValue(val)

    def _flash_done(self, success):
        self.btn_flash.setEnabled(True)
        if success:
            self._set_status("✅  FLASH SUCCESS", "green")
        else:
            self._set_status("❌  FLASH FAILED", "red")

    def _set_status(self, msg, color="black"):
        self.lbl_status.setText(msg)
        self.lbl_status.setStyleSheet(
            "font-weight: bold; font-size: 13px; color: %s;" % color)

    # ── Serial Monitor 콜백 ───────────────────────────────────────────────
    def _toggle_connect(self):
        if self.monitor._running:
            self.monitor.disconnect()
            self.btn_connect.setText("Connect")
            self.btn_connect.setStyleSheet(
                "QPushButton{background:#2e7d32;color:white;border-radius:4px;}"
                "QPushButton:hover{background:#1b5e20;}")
        else:
            port = self.combo_port.currentData()
            if not port:
                self._mon_status("No port selected")
                return
            baud = int(self.combo_baud.currentText())
            self.monitor.connect(port, baud)
            self.btn_connect.setText("Disconnect")
            self.btn_connect.setStyleSheet(
                "QPushButton{background:#c62828;color:white;border-radius:4px;}"
                "QPushButton:hover{background:#b71c1c;}")

    def _mon_send_line(self, text: str):
        self._last_sent = text.strip()   # echo 억제: 마지막 전송 명령 저장
        self.monitor.send(text)

    def _mon_send_bytes(self, data: bytes):
        if self.monitor._serial and self.monitor._serial.is_open:
            try:
                self.monitor._serial.write(data)
            except Exception:
                pass

    def _mon_append(self, text):
        # echo 억제: 방금 보낸 명령이 그대로 돌아오면 무시
        if self._last_sent and text.strip() == self._last_sent:
            self._last_sent = ""
            return
        self.terminal.append_rx(text)

    def _mon_append_prompt(self, text):
        self.terminal.append_prompt(text)

    def _mon_status(self, msg):
        hint = "  |  클릭 후 바로 입력  (Enter=전송  Ctrl+C=인터럽트  Ctrl+L=화면지우기)"
        self.lbl_mon_status.setText(msg + hint)
        if "Connected" in msg and "Dis" not in msg:
            self.lbl_mon_status.setStyleSheet("color:#4caf50;font-size:11px;font-weight:bold;")
            self.terminal.append_status(msg, "#4caf50")
            self.terminal.setFocus()
        else:
            self.lbl_mon_status.setStyleSheet("color:gray;font-size:11px;")
            self.terminal.append_status(msg, "#ff7043")


# ── 엔트리포인트 ───────────────────────────────────────────────────────────
def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = FlashTool()
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
