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
    CELL = auto()


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
            # CELL 모드는 8×8 그리드를 위해 최소 크기 확장
            if mode == DisplayMode.CELL:
                self.setMinimumSize(90, 130)
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
