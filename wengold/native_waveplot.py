"""Zoomable native waveform canvas for the WENGOLD PyQt6 desktop.

Plots real sampled VCD timestamps and high/low/unknown levels. It does not infer
clock periods, interpolate unobserved bus values, or create synthetic signals.
"""
from __future__ import annotations


def build_wave_canvas(QtCore, QtGui, QtWidgets):
    class WaveCanvas(QtWidgets.QWidget):
        signalSelected = QtCore.pyqtSignal(str)

        def __init__(self, parent=None):
            super().__init__(parent)
            self.data = {"signals": [], "times": [], "cycles": 0}
            self.zoom = 1.0
            self.row_height = 38
            self.label_width = 185
            self.slot_width = 55
            self.setMinimumSize(620, 220)
            self.setMouseTracking(True)

        def set_data(self, data):
            self.data = data
            self._resize()
            self.update()

        def set_zoom(self, value):
            self.zoom = max(.5, min(8.0, float(value)))
            self._resize()
            self.update()

        def _resize(self):
            count = self.data.get("cycles", 0)
            width = max(620, self.label_width + int(max(2, count) * self.slot_width * self.zoom))
            height = max(180, 44 + len(self.data.get("signals", [])) * self.row_height)
            self.setMinimumSize(width, height)
            self.resize(width, height)
            self.updateGeometry()

        def mousePressEvent(self, event):
            row = int((event.position().y() - 44) // self.row_height)
            signals = self.data.get("signals", [])
            if 0 <= row < len(signals):
                self.signalSelected.emit(signals[row]["name"])
            super().mousePressEvent(event)

        def paintEvent(self, event):
            painter = QtGui.QPainter(self)
            painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, False)
            painter.fillRect(self.rect(), QtGui.QColor("#fffef9"))
            signals = self.data.get("signals", [])
            timestamps = self.data.get("times", [])
            if not signals:
                painter.setPen(QtGui.QColor("#746c4e"))
                painter.drawText(18, 32, "No VCD samples loaded")
                painter.end()
                return

            painter.fillRect(0, 0, self.width(), 44, QtGui.QColor("#fff1b9"))
            painter.fillRect(0, 0, self.label_width, self.height(), QtGui.QColor("#fff9e5"))
            painter.setPen(QtGui.QColor("#6d5916"))
            painter.drawText(10, 25, "SIGNALS")
            sample_step = self.slot_width * self.zoom
            count = min(self.data.get("cycles", 0), 600)
            for i in range(count):
                x = self.label_width + round(i * sample_step)
                if i % max(1, round(100 / sample_step)) == 0:
                    painter.setPen(QtGui.QColor("#e9d9ab"))
                    painter.drawLine(x, 44, x, self.height())
                    label = str(timestamps[i]) if i < len(timestamps) else str(i)
                    painter.setPen(QtGui.QColor("#67572c"))
                    painter.drawText(x + 3, 17, label)
            for row, signal in enumerate(signals):
                y = 44 + row * self.row_height
                if row % 2:
                    painter.fillRect(0, y, self.width(), self.row_height, QtGui.QColor("#fffbea"))
                painter.setPen(QtGui.QColor("#4e452f"))
                painter.drawText(8, y + 23, str(signal.get("name", ""))[:26])
                painter.setPen(QtGui.QColor("#e5dbb8"))
                painter.drawLine(0, y + self.row_height, self.width(), y + self.row_height)
                values = signal.get("values", [])[:count]
                width = int(signal.get("width", 1))
                if width == 1:
                    for i, value in enumerate(values):
                        x = self.label_width + round(i * sample_step)
                        nxt = self.label_width + round((i + 1) * sample_step)
                        level = y + (8 if value == 1 else 29 if value == 0 else 19)
                        painter.setPen(QtGui.QPen(QtGui.QColor("#af8500" if value is not None else "#b64735"), 2))
                        painter.drawLine(x, level, nxt, level)
                        if i and value != values[i - 1]:
                            prev = y + (8 if values[i - 1] == 1 else 29 if values[i - 1] == 0 else 19)
                            painter.drawLine(x, prev, x, level)
                else:
                    for i, value in enumerate(values):
                        x = self.label_width + round(i * sample_step)
                        cell = max(2, round(sample_step))
                        painter.setPen(QtGui.QColor("#c8ae60"))
                        painter.drawRect(x, y + 6, cell, 25)
                        painter.setPen(QtGui.QColor("#624c10"))
                        text = "X" if value is None else hex(value)
                        painter.drawText(x + 4, y + 22, text[:max(1, int(cell / 7))])
            painter.setPen(QtGui.QColor("#b9aa7b"))
            painter.drawLine(self.label_width, 0, self.label_width, self.height())
            painter.end()

    return WaveCanvas()
