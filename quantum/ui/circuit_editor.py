"""PyQt6 drag-and-drop circuit editor with explicit multi-qubit IR mapping."""
from __future__ import annotations
import uuid

from quantum.core.circuit_ir import Circuit, Operation, validate_circuit


def build_editor(QtWidgets):
    from PyQt6 import QtCore, QtGui

    gate_arity = {
        "H": 1, "X": 1, "Y": 1, "Z": 1, "S": 1, "T": 1,
        "RX": 1, "RY": 1, "RZ": 1, "CNOT": 2, "CZ": 2,
        "SWAP": 2, "CCX": 3, "MEASURE": 1,
    }

    class GateButton(QtWidgets.QPushButton):
        def __init__(self, gate, parent=None):
            super().__init__(gate, parent)
            self.gate = gate
            self._press_pos = None

        def mousePressEvent(self, event):
            if event.button() == QtCore.Qt.MouseButton.LeftButton:
                self._press_pos = event.position().toPoint()
            super().mousePressEvent(event)

        def mouseMoveEvent(self, event):
            if (self._press_pos is not None
                    and event.buttons() & QtCore.Qt.MouseButton.LeftButton
                    and (event.position().toPoint() - self._press_pos).manhattanLength()
                    >= QtWidgets.QApplication.startDragDistance()):
                mime = QtCore.QMimeData()
                mime.setText(self.gate)
                drag = QtGui.QDrag(self)
                drag.setMimeData(mime)
                drag.exec(QtCore.Qt.DropAction.CopyAction)
                self._press_pos = None
            super().mouseMoveEvent(event)

    class CircuitCanvas(QtWidgets.QGraphicsView):
        def __init__(self, parent=None):
            self.scene = QtWidgets.QGraphicsScene(parent)
            super().__init__(self.scene, parent)
            self.setAcceptDrops(True)
            self.num_qubits = 3
            self.operations = []
            self.setMinimumSize(650, 320)
            self.setSceneRect(0, 0, 980, 280)
            self.render_circuit()

        def dragEnterEvent(self, event):
            if event.mimeData().hasText() and event.mimeData().text().upper() in gate_arity:
                event.acceptProposedAction()

        def dragMoveEvent(self, event):
            event.acceptProposedAction()

        def _operands(self, gate, anchor):
            arity = gate_arity[gate]
            if arity == 1:
                return [anchor]
            candidates = [q for q in range(self.num_qubits) if q != anchor]
            if gate == "CNOT":
                return [candidates[0], anchor]  # control, target
            if gate == "CCX":
                return [candidates[0], candidates[1], anchor]  # controls, target
            return [anchor, candidates[0]]  # two targets

        def dropEvent(self, event):
            gate = event.mimeData().text().upper()
            if gate not in gate_arity:
                event.ignore()
                return
            point = self.mapToScene(event.position().toPoint())
            anchor = max(0, min(self.num_qubits - 1, round((point.y() - 45) / 75)))
            column = max(0, round((point.x() - 100) / 95))
            operands = self._operands(gate, anchor)
            self.operations.append({
                "id": uuid.uuid4().hex,
                "gate": gate,
                "qubits": operands,
                "column": column,
            })
            self.render_circuit()
            event.acceptProposedAction()

        def to_circuit(self):
            operations = []
            for item in self.operations:
                gate, qubits = item["gate"], item["qubits"]
                if gate == "CNOT":
                    op = Operation(item["id"], gate, targets=(qubits[1],), controls=(qubits[0],))
                elif gate == "CCX":
                    op = Operation(item["id"], gate, targets=(qubits[2],), controls=(qubits[0], qubits[1]))
                elif gate in {"CZ", "SWAP"}:
                    op = Operation(item["id"], gate, targets=tuple(qubits))
                elif gate == "MEASURE":
                    op = Operation(item["id"], gate, targets=(qubits[0],),
                                   classical_bits=(qubits[0],))
                else:
                    op = Operation(item["id"], gate, targets=(qubits[0],))
                operations.append(op)
            circuit = Circuit("quantum-editor", self.num_qubits, tuple(operations),
                              num_clbits=self.num_qubits)
            validate_circuit(circuit)
            return circuit

        def render_circuit(self):
            self.scene.clear()
            for qubit in range(self.num_qubits):
                y = 45 + qubit * 75
                self.scene.addText(f"q[{qubit}]").setPos(8, y - 13)
                self.scene.addLine(65, y, 950, y)
            for item in self.operations:
                x = 100 + item["column"] * 95
                gate, qubits = item["gate"], item["qubits"]
                ys = [45 + q * 75 for q in qubits]
                if len(ys) > 1:
                    self.scene.addLine(x, min(ys), x, max(ys))
                if gate == "CNOT":
                    self.scene.addEllipse(x - 5, ys[0] - 5, 10, 10)
                    self.scene.addEllipse(x - 11, ys[1] - 11, 22, 22)
                    self.scene.addLine(x - 8, ys[1], x + 8, ys[1])
                    self.scene.addLine(x, ys[1] - 8, x, ys[1] + 8)
                elif gate == "CCX":
                    for y in ys[:2]:
                        self.scene.addEllipse(x - 5, y - 5, 10, 10)
                    self.scene.addEllipse(x - 11, ys[2] - 11, 22, 22)
                    self.scene.addLine(x - 8, ys[2], x + 8, ys[2])
                    self.scene.addLine(x, ys[2] - 8, x, ys[2] + 8)
                else:
                    rect_y = ys[0] - 19
                    self.scene.addRect(x - 24, rect_y, 48, 38)
                    self.scene.addText(gate).setPos(x - 18, rect_y + 6)

    root = QtWidgets.QWidget()
    layout = QtWidgets.QHBoxLayout(root)
    palette = QtWidgets.QVBoxLayout()
    palette.addWidget(QtWidgets.QLabel("GATE LIBRARY"))
    for gate in gate_arity:
        palette.addWidget(GateButton(gate))
    palette.addStretch(1)
    canvas = CircuitCanvas()
    layout.addLayout(palette)
    tabs = QtWidgets.QTabWidget()
    tabs.addTab(canvas, "Circuit")
    try:
        from quantum.ui.state_visualizer import build_state_visualizer
        state_visualizer = build_state_visualizer(QtWidgets)
    except ImportError:
        state_visualizer = QtWidgets.QWidget()
        state_layout = QtWidgets.QVBoxLayout(state_visualizer)
        state_layout.addWidget(QtWidgets.QLabel(
            "Install the quantum extra to enable Bloch sphere and Q-sphere plots."
        ))
        state_visualizer.set_statevector = lambda state: None
    tabs.addTab(state_visualizer, "State Visualizer")
    layout.addWidget(tabs, 1)
    root.canvas = canvas
    root.to_circuit = canvas.to_circuit
    root.state_visualizer = state_visualizer
    root.set_statevector = state_visualizer.set_statevector
    return root
