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
from PySide6.QtCore import Qt, QRectF, Slot, QPointF


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
    COLOR_SAFE       = QColor("#1E88E5")
    COLOR_BACKGROUND = QColor("#444")
    COLOR_GRID_LINE  = QColor("#2E2E2E")


class DisplayMode(Enum):
    BAR  = auto()
    LINE = auto()


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
    """S2 센서 1개의 8열 거리 데이터를 수직 막대 또는 선으로 표시"""

    def __init__(self, sensor_name: str, parent=None):
        super().__init__(parent)
        self.sensor_name  = sensor_name
        self.distances    = [4000] * 8
        self.display_mode = DisplayMode.BAR
        self.setMinimumSize(60, 200)

    @Slot(list)
    def update_data(self, new_distances: list):
        if len(new_distances) == 8:
            self.distances = new_distances
            self.update()

    @Slot(DisplayMode)
    def setDisplayMode(self, mode: DisplayMode):
        if self.display_mode != mode:
            self.display_mode = mode
            self.update()

    @staticmethod
    def _color(dist: int) -> QColor:
        if dist < Constants.OBSTACLE_DIST_CRITICAL: return Constants.COLOR_CRITICAL
        if dist < Constants.OBSTACLE_DIST_WARNING:  return Constants.COLOR_WARNING
        if dist < Constants.OBSTACLE_DIST_CAUTION:  return Constants.COLOR_CAUTION
        if dist < Constants.OBSTACLE_DIST_NORMAL:   return Constants.COLOR_NORMAL
        return Constants.COLOR_SAFE

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        painter.setPen(Qt.white)
        painter.drawText(self.rect(), Qt.AlignHCenter | Qt.AlignTop, self.sensor_name)

        bar_h   = self.height() - 20
        bar_w   = self.width() / 8.0
        max_d   = 4000.0

        if self.display_mode == DisplayMode.BAR:
            for i, d in enumerate(self.distances):
                painter.setBrush(self._color(d))
                painter.setPen(Qt.NoPen)
                ratio = 1.0 - min(d, max_d) / max_d
                h     = bar_h * ratio
                painter.drawRect(QRectF(i * bar_w,
                                        self.height() - h,
                                        bar_w - 2, h))
        else:
            pts = []
            for i, d in enumerate(self.distances):
                ratio = 1.0 - min(d, max_d) / max_d
                pts.append(QPointF((i + 0.5) * bar_w, self.height() - bar_h * ratio))
            path = QPainterPath()
            path.moveTo(pts[0])
            for p in pts[1:]:
                path.lineTo(p)
            painter.setPen(QPen(Constants.COLOR_CAUTION, 2))
            painter.drawPath(path)


# ── 3. 컬러바 범례 ────────────────────────────────────────────────────────────
class ColorBarWidget(QWidget):
    """히트맵 거리-색상 범례"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(40, 280)

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
        for text, pos in {"0m": 1.0, "0.3m": 1 - 300/4000,
                           "1m": 1 - 1000/4000, "2m": 1 - 2000/4000,
                           "4m+": 0.0}.items():
            painter.drawText(22, int(rect.height() * pos) + 5, text)
