"""
view/widgets.py
monitor_ux.py 에서 추출한 커스텀 위젯 모음.
비즈니스 로직 없음 — 순수 그리기/표시만 담당.
"""

import math
from enum import Enum, auto

from PySide6.QtWidgets import QWidget
from PySide6.QtGui import (
    QPainter, QColor, QBrush, QPen,
    QLinearGradient, QPainterPath,
)
from PySide6.QtCore import Qt, QRectF, Slot, QPointF, QTimer


# ── 공통 상수 ─────────────────────────────────────────────────────────────────
class Constants:
    TILT_ANGLE_NORMAL  = 5
    TILT_ANGLE_WARNING = 15

    OBSTACLE_DIST_CRITICAL = 300
    OBSTACLE_DIST_WARNING  = 600
    OBSTACLE_DIST_CAUTION  = 1000
    OBSTACLE_DIST_NORMAL   = 2000

    COLOR_CRITICAL   = QColor("#F44336")
    COLOR_WARNING    = QColor("#FF9800")
    COLOR_CAUTION    = QColor("#FFC107")
    COLOR_NORMAL     = QColor("#4CAF50")
    COLOR_SAFE       = QColor("#004D5A")
    COLOR_BACKGROUND = QColor("#444")
    COLOR_GRID_LINE  = QColor("#2E2E2E")


class DisplayMode(Enum):
    BAR  = auto()
    LINE = auto()
    CELL = auto()
    ISO  = auto()   # 아이소메트릭 3D 막대 차트


# ── 0. 센서 상태 인디케이터 (Blink Dot) ──────────────────────────────────────
class BlinkDot(QWidget):
    """작은 원형 인디케이터 + 하단 레이블.
    set_connected(bool)  : MQTT 연결 상태 (녹색 ↔ 회색)
    set_mapped(bool)     : config 매핑 여부 (파란색 ↔ 어두운 회색)
    blink()              : 150ms 노란색 플래시 후 base 색으로 복귀
    """
    _C_OFF      = QColor("#3a3a3a")
    _C_MAPPED   = QColor("#1565C0")
    _C_CONN     = QColor("#2e7d32")
    _C_BLINK    = QColor("#FFD600")

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self._label      = label
        self._base_color = self._C_OFF
        self._color      = self._C_OFF
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._on_blink_end)
        self.setFixedSize(32, 36)

    def set_connected(self, connected: bool):
        self._base_color = self._C_CONN if connected else self._C_OFF
        self._refresh()

    def set_mapped(self, mapped: bool):
        self._base_color = self._C_MAPPED if mapped else self._C_OFF
        self._refresh()

    def blink(self):
        self._color = self._C_BLINK
        self._timer.start()
        self.update()

    def _on_blink_end(self):
        self._color = self._base_color
        self.update()

    def _refresh(self):
        if not self._timer.isActive():
            self._color = self._base_color
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        r  = 7
        cx = self.width() // 2
        painter.setBrush(QBrush(self._color))
        painter.setPen(QPen(QColor("#222"), 1))
        painter.drawEllipse(QPointF(cx, r + 2), r, r)
        painter.setPen(QPen(Qt.white))
        f = painter.font()
        f.setPointSize(6)
        painter.setFont(f)
        painter.drawText(0, r * 2 + 5, self.width(), 14,
                         Qt.AlignHCenter | Qt.AlignVCenter, self._label)


# ── 1. 기울기 표시 위젯 ───────────────────────────────────────────────────────
class TiltIndicatorWidget(QWidget):
    """두 TFmini 센서 거리값으로 계산된 기울기 각도를 버블 레벨로 표시"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._angle = 0.0
        self.setMinimumSize(300, 60)

    @Slot(float)
    def setAngle(self, angle: float):
        if self._angle != angle:
            self._angle = angle
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        painter.fillRect(rect, Constants.COLOR_BACKGROUND)

        # 눈금
        painter.setPen(QPen(Qt.white, 1, Qt.DotLine))
        cx = rect.center().x()
        for pos in (-0.5, -0.25, 0, 0.25, 0.5):
            x = cx + pos * rect.width() * 0.8
            painter.drawLine(int(x), int(rect.height() * 0.2),
                             int(x), int(rect.height() * 0.8))

        # 버블 색상
        if abs(self._angle) < Constants.TILT_ANGLE_NORMAL:
            color = Constants.COLOR_NORMAL
        elif abs(self._angle) < Constants.TILT_ANGLE_WARNING:
            color = Constants.COLOR_CAUTION
        else:
            color = Constants.COLOR_CRITICAL

        painter.setBrush(QBrush(color))
        painter.setPen(Qt.NoPen)

        r  = 18
        cy = rect.center().y()
        max_off = rect.width() / 2 - r - 5
        off = (self._angle / 45.0) * max_off
        bx  = rect.center().x() + off
        br  = QRectF(bx - r, cy - r, r * 2, r * 2)
        painter.drawEllipse(br)

        painter.setPen(QPen(Qt.white))
        f = painter.font(); f.setBold(True); painter.setFont(f)
        painter.drawText(br, Qt.AlignCenter, f"{self._angle:.1f}°")


# ── 2. 장애물 감지 위젯 (수직 막대 / 선 그래프) ───────────────────────────────
class ObstacleColumnWidget(QWidget):
    """S2 센서 1개의 8열 거리 데이터를 수직 막대 또는 선으로 표시

    레이아웃 (위 → 아래):
      [  센서 이름  ]   ← 16px
      [  막대/선    ]   ← 중간 영역 (bar_area)
      [최솟값 mm    ]   ← 16px
    """

    _LABEL_H = 16   # 위 제목 높이
    _VALUE_H = 16   # 아래 수치 높이

    def __init__(self, sensor_name: str, parent=None):
        super().__init__(parent)
        self.sensor_name  = sensor_name
        self.distances    = [4000] * 8    # 8열 최솟값 (BAR/LINE)
        self.raw64        = [4000] * 64   # 전체 64존 (CELL)
        self.display_mode = DisplayMode.BAR
        self.setMinimumSize(70, 220)

    @Slot(list)
    def update_data(self, new_d64: list):
        """64개 원본값을 받아 BAR/LINE용 8열 최솟값도 함께 갱신"""
        d = list(new_d64) + [4000] * max(0, 64 - len(new_d64))
        self.raw64 = d[:64]
        # 8열 최솟값: col별 8개 row 중 min
        self.distances = [
            min(self.raw64[row * 8 + col] for row in range(8))
            for col in range(8)
        ]
        self.update()

    def setDisplayMode(self, mode: DisplayMode):
        if self.display_mode != mode:
            self.display_mode = mode
            if mode == DisplayMode.CELL:
                self.setMinimumSize(90, 130)
            elif mode == DisplayMode.ISO:
                self.setMinimumSize(110, 180)
            else:
                self.setMinimumSize(70, 220)
            self.update()

    @staticmethod
    def _color(dist: int) -> QColor:
        if dist < Constants.OBSTACLE_DIST_CRITICAL: return Constants.COLOR_CRITICAL
        if dist < Constants.OBSTACLE_DIST_WARNING:  return Constants.COLOR_WARNING
        if dist < Constants.OBSTACLE_DIST_CAUTION:  return Constants.COLOR_CAUTION
        if dist < Constants.OBSTACLE_DIST_NORMAL:   return Constants.COLOR_NORMAL
        return Constants.COLOR_SAFE

    def _paint_iso(self, painter: QPainter, w: int, h: int, bar_top: int, bar_bot: int):
        """8×8 아이소메트릭 3D 막대 차트 (전체 64존 raw64).

        타일 배치 (col=오른쪽, row=아래쪽으로 갈수록 앞쪽):
          sx = cx + (col - row) * cw
          sy = cy + (col + row) * ch
        렌더링 순서: (col+row) 오름차순 → 뒤에서 앞으로 그려 occlusion 보정.
        """
        avail_h = bar_bot - bar_top
        cw      = max(4, w // 16)              # 타일 반폭 (픽셀)
        ch      = max(2, cw // 2)              # 타일 반높이 (2:1 isometric)
        max_bar = max(8, avail_h - 14 * ch - 8)  # 최대 바 픽셀 높이
        cx      = w // 2
        cy      = bar_top + max_bar + 4        # 그리드 북쪽 꼭짓점 기준 y
        max_dist = 4000.0

        # 뒤에서 앞으로: (col+row) 오름차순
        for diag in range(15):
            for row in range(max(0, diag - 7), min(8, diag + 1)):
                col = diag - row
                if not (0 <= col < 8):
                    continue

                d    = self.raw64[row * 8 + col]
                h_px = int(max_bar * max(0.0, 1.0 - min(d, max_dist) / max_dist))
                base = self._color(d)
                sx   = cx + (col - row) * cw
                sy   = cy + (col + row) * ch

                # 상단면 꼭짓점 (바 높이 h_px 만큼 위로 이동)
                top = [
                    QPointF(sx,      sy - ch - h_px),  # north
                    QPointF(sx + cw, sy      - h_px),  # east
                    QPointF(sx,      sy + ch - h_px),  # south
                    QPointF(sx - cw, sy      - h_px),  # west
                ]

                edge_pen = QPen(QColor("#0d0d0d"), 0.3)

                if h_px > 1:
                    # 오른쪽 측면 (east-south, 밝은 어두움)
                    r_pts = [top[1], top[2],
                             QPointF(sx,      sy + ch),
                             QPointF(sx + cw, sy)]
                    path = QPainterPath()
                    path.moveTo(r_pts[0])
                    for p in r_pts[1:]:
                        path.lineTo(p)
                    path.closeSubpath()
                    painter.setBrush(QBrush(base.darker(150)))
                    painter.setPen(edge_pen)
                    painter.drawPath(path)

                    # 왼쪽 측면 (west-south, 더 어두움)
                    l_pts = [top[3], top[2],
                             QPointF(sx,      sy + ch),
                             QPointF(sx - cw, sy)]
                    path = QPainterPath()
                    path.moveTo(l_pts[0])
                    for p in l_pts[1:]:
                        path.lineTo(p)
                    path.closeSubpath()
                    painter.setBrush(QBrush(base.darker(190)))
                    painter.setPen(edge_pen)
                    painter.drawPath(path)

                # 상단면 (항상 그림 — h_px=0이면 평면 다이아몬드)
                path = QPainterPath()
                path.moveTo(top[0])
                for p in top[1:]:
                    path.lineTo(p)
                path.closeSubpath()
                painter.setBrush(QBrush(base))
                painter.setPen(edge_pen)
                painter.drawPath(path)

        # 최솟값 텍스트 (하단)
        min_d = min(self.raw64)
        painter.setPen(QPen(self._color(min_d)))
        f = painter.font(); f.setPointSize(8); f.setBold(True); painter.setFont(f)
        painter.drawText(0, bar_bot, w, self._VALUE_H,
                         Qt.AlignHCenter | Qt.AlignVCenter, f"{min_d} mm")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        h = self.height()

        # ── 배경 ──────────────────────────────────────────────────────
        painter.fillRect(self.rect(), Constants.COLOR_BACKGROUND)

        # ── 센서 이름 (상단) ──────────────────────────────────────────
        painter.setPen(QPen(Qt.white))
        f = painter.font(); f.setPointSize(8); painter.setFont(f)
        painter.drawText(0, 0, w, self._LABEL_H,
                         Qt.AlignHCenter | Qt.AlignVCenter, self.sensor_name)

        # ── 막대 영역 ─────────────────────────────────────────────────
        bar_top  = self._LABEL_H
        bar_bot  = h - self._VALUE_H
        bar_h    = bar_bot - bar_top    # 실제 그래프 세로 길이
        bar_w    = w / 8.0
        max_d    = 4000.0

        # ── ISO 모드 조기 리턴 ────────────────────────────────────────
        if self.display_mode == DisplayMode.ISO:
            self._paint_iso(painter, w, h, bar_top, bar_bot)
            return

        if self.display_mode == DisplayMode.BAR:
            for i, d in enumerate(self.distances):
                color = self._color(d)
                painter.setBrush(QBrush(color))
                painter.setPen(Qt.NoPen)
                ratio = 1.0 - min(d, max_d) / max_d
                fill_h = bar_h * ratio
                painter.drawRect(QRectF(
                    i * bar_w,
                    bar_bot - fill_h,
                    bar_w - 1,
                    fill_h,
                ))
        else:  # LINE
            pts = []
            for i, d in enumerate(self.distances):
                ratio = 1.0 - min(d, max_d) / max_d
                pts.append(QPointF((i + 0.5) * bar_w, bar_bot - bar_h * ratio))
            if pts:
                # 선 색상: 최솟값 기준
                min_d = min(self.distances)
                painter.setPen(QPen(self._color(min_d), 2))
                path = QPainterPath()
                path.moveTo(pts[0])
                for p in pts[1:]:
                    path.lineTo(p)
                painter.drawPath(path)
                # 포인트 점
                painter.setBrush(QBrush(self._color(min_d)))
                for p in pts:
                    painter.drawEllipse(p, 3, 3)

        if self.display_mode == DisplayMode.CELL:
            # 8×8 히트맵 그리드
            cell_w = w / 8.0
            cell_h = bar_h / 8.0
            painter.setPen(Qt.NoPen)
            for row in range(8):
                for col in range(8):
                    d = self.raw64[row * 8 + col]
                    painter.setBrush(QBrush(self._color(d)))
                    painter.drawRect(QRectF(
                        col * cell_w + 0.5,
                        bar_top + row * cell_h + 0.5,
                        cell_w - 1,
                        cell_h - 1,
                    ))
            # 최솟값 표시 후 리턴 (격자선 스킵)
            min_d = min(self.raw64)
            color_txt = self._color(min_d)
            painter.setPen(QPen(color_txt))
            f2 = painter.font(); f2.setPointSize(8); f2.setBold(True); painter.setFont(f2)
            painter.drawText(0, bar_bot, w, self._VALUE_H,
                             Qt.AlignHCenter | Qt.AlignVCenter,
                             f"{min_d} mm")
            return

        # ── 격자선 (bar_area 내) ───────────────────────────────────────
        painter.setPen(QPen(Constants.COLOR_GRID_LINE, 1))
        for frac in (0.25, 0.5, 0.75):
            y = int(bar_bot - bar_h * frac)
            painter.drawLine(0, y, w, y)

        # ── 최솟값 표시 (하단) ────────────────────────────────────────
        min_d = min(self.distances)
        color_txt = self._color(min_d)
        painter.setPen(QPen(color_txt))
        f2 = painter.font(); f2.setPointSize(8); f2.setBold(True); painter.setFont(f2)
        painter.drawText(0, bar_bot, w, self._VALUE_H,
                         Qt.AlignHCenter | Qt.AlignVCenter,
                         f"{min_d} mm")


# ── 3. 컬러바 범례 ────────────────────────────────────────────────────────────
class ColorBarWidget(QWidget):
    """히트맵 거리-색상 범례"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(50, 280)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()

        grad = QLinearGradient(0, rect.height(), 0, 0)
        grad.setColorAt(0,                                         Constants.COLOR_SAFE)
        grad.setColorAt(1.0 - Constants.OBSTACLE_DIST_NORMAL   / 4000.0, Constants.COLOR_SAFE)
        grad.setColorAt(1.0 - Constants.OBSTACLE_DIST_CAUTION  / 4000.0, Constants.COLOR_NORMAL)
        grad.setColorAt(1.0 - Constants.OBSTACLE_DIST_WARNING  / 4000.0, Constants.COLOR_CAUTION)
        grad.setColorAt(1.0 - Constants.OBSTACLE_DIST_CRITICAL / 4000.0, Constants.COLOR_WARNING)
        grad.setColorAt(1.0,                                       Constants.COLOR_CRITICAL)
        painter.fillRect(QRectF(0, 0, 20, rect.height()), grad)

        painter.setPen(Qt.white)
        f = painter.font(); f.setPointSize(8); painter.setFont(f)
        lh = 14  # 레이블 행 높이
        # 그라디언트 방향: 위=0m(위험), 아래=4m+(안전) — 레이블도 동일하게
        for text, ratio in [("0m", 0.0), ("0.3m", 300/4000),
                            ("1m", 1000/4000), ("2m", 2000/4000),
                            ("4m+", 1.0)]:
            cy = int(rect.height() * ratio)
            ty = max(0, min(cy - lh // 2, int(rect.height()) - lh))
            painter.drawText(22, ty, int(rect.width()) - 22, lh,
                             Qt.AlignVCenter | Qt.AlignLeft, text)
