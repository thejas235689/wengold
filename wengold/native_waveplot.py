"""Qt waveform canvas with bounded viewport painting and two sample cursors."""
from __future__ import annotations

from .wave_inspect import logic_at, render_value


def build_wave_canvas(QtCore, QtGui, QtWidgets):
    class WaveCanvas(QtWidgets.QWidget):
        signalSelected = QtCore.pyqtSignal(str)
        cursorSelected = QtCore.pyqtSignal(int, bool)

        def __init__(self):
            super().__init__()
            self.data = {"signals": [], "times": [], "cycles": 0}
            self.visible_signals = []
            self.cursors = (None, None)
            self.radix = "Hex"
            self.zoom = 1.0
            self.row_height = 35
            self.label_width = 182
            self.slot_width = 55
            self.ruler_height = 32
            self.setAccessibleName("Waveform timeline")
            self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed,
                               QtWidgets.QSizePolicy.Policy.Fixed)
            self._resize()

        @property
        def step(self):
            return self.slot_width * self.zoom

        def sample_x(self, index):
            return self.label_width + round(index * self.step)

        def set_data(self, data):
            self.data = data
            self.visible_signals = data["signals"]
            self.cursors = None, None
            self._resize()
            self.update()

        def set_signals(self, signals):
            self.visible_signals = signals
            self._resize()
            self.update()

        def set_zoom(self, value):
            self.zoom = max(.25, min(8.0, float(value)))
            self._resize()
            self.update()

        def _resize(self):
            self.setFixedSize(max(440, self.sample_x(self.data["cycles"]) + 12),
                              max(155, self.ruler_height + len(self.visible_signals) * self.row_height + 6))

        def mousePressEvent(self, event):
            x, y = event.position().x(), event.position().y()
            row = int((y - self.ruler_height) // self.row_height)
            if 0 <= row < len(self.visible_signals):
                self.signalSelected.emit(self.visible_signals[row]["name"])
            if x >= self.label_width and self.data["cycles"] and event.button() in (
                    QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.MouseButton.RightButton):
                index = min(self.data["cycles"] - 1, int((x - self.label_width) / self.step))
                set_b = (event.button() == QtCore.Qt.MouseButton.RightButton or
                         bool(event.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier))
                self.cursorSelected.emit(index, set_b)
            super().mousePressEvent(event)

        def paintEvent(self, event):
            painter = QtGui.QPainter(self)
            rect = event.rect()
            color = QtGui.QColor
            painter.fillRect(rect, color("#ffffff"))
            count = self.data["cycles"]
            if not self.visible_signals or not count:
                painter.setPen(color("#516079"))
                painter.drawText(12, 27, "No matching signals" if count else "Load a VCD or FST to inspect its signals")
                return
            ruler = self.ruler_height
            first = max(0, int((rect.left() - self.label_width) // self.step))
            stop = min(count, int((rect.right() - self.label_width) // self.step) + 1)
            first_row = max(0, (rect.top() - ruler) // self.row_height)
            stop_row = min(len(self.visible_signals), (rect.bottom() - ruler) // self.row_height + 1)
            painter.fillRect(0, 0, self.width(), ruler, color("#e8eef8"))
            painter.fillRect(0, ruler, self.label_width, self.height() - ruler, color("#f1f5fc"))
            painter.setPen(color("#435674"))
            painter.drawText(8, 21, self.data.get("ruler", "SIGNAL  /  TRACE TICKS"))
            font = painter.fontMetrics()
            tick_spacing = max(1, round(95 / self.step))
            for row in range(first_row, stop_row):
                y = ruler + row * self.row_height
                if row % 2:
                    painter.fillRect(self.label_width, y, self.width() - self.label_width,
                                     self.row_height, color("#f5f8fd"))
                painter.setPen(color("#dde5f2"))
                painter.drawLine(0, y + self.row_height - 1, self.width(), y + self.row_height - 1)
                sig = self.visible_signals[row]
                painter.setPen(color("#354963"))
                painter.drawText(8, y + 22, font.elidedText(
                    sig["name"], QtCore.Qt.TextElideMode.ElideLeft, self.label_width - 15))
            for i in range(first, stop):
                x = self.sample_x(i)
                if i % tick_spacing == 0:
                    painter.setPen(color("#dce5f3"))
                    painter.drawLine(x, ruler, x, self.height())
                    painter.setPen(color("#435674"))
                    painter.drawText(x + 3, 19, str(self.data["times"][i]))
            for row in range(first_row, stop_row):
                sig = self.visible_signals[row]
                y = ruler + row * self.row_height
                for i in range(first, stop):
                    left, right = self.sample_x(i), self.sample_x(i + 1)
                    bits = logic_at(sig, i)
                    if sig["width"] == 1:
                        levels = {"1": 7, "0": 27, "x": 14, "z": 20}
                        colors = {"x": "#b63236", "z": "#7651ad"}
                        level = y + levels[bits]
                        pen = QtGui.QPen(color(colors.get(bits, "#2458a6")), 2)
                        if bits in "xz":
                            pen.setStyle(QtCore.Qt.PenStyle.DashLine)
                        painter.setPen(pen)
                        painter.drawLine(left, level, right, level)
                        if i:
                            before = logic_at(sig, i - 1)
                            if bits != before:
                                painter.drawLine(left, y + levels[before], left, level)
                    else:
                        edge = min(4, (right - left) // 3)
                        painter.setPen(color("#b63236" if "x" in bits else
                                             "#7651ad" if "z" in bits else "#4169a5"))
                        painter.drawPolygon(QtGui.QPolygon([
                            QtCore.QPoint(left, y + 17), QtCore.QPoint(left + edge, y + 6),
                            QtCore.QPoint(right - edge, y + 6), QtCore.QPoint(right, y + 17),
                            QtCore.QPoint(right - edge, y + 28), QtCore.QPoint(left + edge, y + 28),
                        ]))
                        if right - left > 18:
                            painter.drawText(left + 5, y + 22, font.elidedText(
                                render_value(sig, i, self.radix)[:256],
                                QtCore.Qt.TextElideMode.ElideRight, right - left - 10))
            for index, marker, marker_color in zip(self.cursors, "AB", ("#0d766b", "#a94a15")):
                if index is not None and first <= index < stop:
                    x = self.sample_x(index)
                    painter.setPen(QtGui.QPen(color(marker_color), 2))
                    painter.drawLine(x, ruler - 4, x, self.height())
                    painter.drawText(x + (4 if marker == "A" else 16), ruler - 5, marker)
            painter.setPen(color("#bac9df"))
            painter.drawLine(self.label_width, 0, self.label_width, self.height())

    return WaveCanvas()
