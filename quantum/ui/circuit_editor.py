"""PyQt6 drag-and-drop circuit editor with explicit multi-qubit IR mapping."""
from __future__ import annotations
import uuid

from quantum.core.circuit_ir import Circuit, Operation, validate_circuit


def build_editor(QtWidgets):
    from PyQt6 import QtCore, QtGui

    gate_arity = {
        "H": 1, "X": 1, "Y": 1, "Z": 1, "S": 1, "SDG": 1, "T": 1, "TDG": 1,
        "RX": 1, "RY": 1, "RZ": 1, "CNOT": 2, "CZ": 2,
        "SWAP": 2, "CCX": 3, "CSWAP": 3, "MEASURE": 1,
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
            if gate == "CSWAP":
                return [candidates[0], anchor, candidates[1]]  # control, swap targets
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
                elif gate == "CSWAP":
                    op = Operation(item["id"], gate, targets=(qubits[1], qubits[2]), controls=(qubits[0],))
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
                elif gate == "CSWAP":
                    self.scene.addEllipse(x - 5, ys[0] - 5, 10, 10)
                    for y in ys[1:]:
                        self.scene.addLine(x - 8, y - 8, x + 8, y + 8)
                        self.scene.addLine(x - 8, y + 8, x + 8, y - 8)
                else:
                    rect_y = ys[0] - 19
                    self.scene.addRect(x - 24, rect_y, 48, 38)
                    self.scene.addText(gate).setPos(x - 18, rect_y + 6)

    class SimulationWorker(QtCore.QThread):
        result_ready = QtCore.pyqtSignal(object)
        failed = QtCore.pyqtSignal(str)

        def __init__(self, backend_name, circuit, shots, seed):
            super().__init__()
            self.backend_name = backend_name
            self.circuit = circuit
            self.shots = shots
            self.seed = seed

        def run(self):
            try:
                from quantum.backends.registry import create_backend
                backend = create_backend(self.backend_name)
                self.result_ready.emit(backend.run(
                    self.circuit, shots=self.shots, seed=self.seed
                ))
            except Exception as exc:
                self.failed.emit(str(exc))

    root = QtWidgets.QWidget()
    outer = QtWidgets.QVBoxLayout(root)
    controls = QtWidgets.QHBoxLayout()
    backend_combo = QtWidgets.QComboBox()
    for backend_name in ("qiskit", "cirq", "quest"):
        backend_combo.addItem(backend_name.upper(), backend_name)
    shots_input = QtWidgets.QSpinBox()
    shots_input.setRange(1, 1000000)
    shots_input.setValue(1024)
    run_button = QtWidgets.QPushButton("Run simulation")
    status_label = QtWidgets.QLabel("Ready — drag gates onto the circuit wires.")
    controls.addWidget(QtWidgets.QLabel("Backend"))
    controls.addWidget(backend_combo)
    controls.addWidget(QtWidgets.QLabel("Shots"))
    controls.addWidget(shots_input)
    controls.addWidget(run_button)
    outer.addLayout(controls)

    content = QtWidgets.QHBoxLayout()
    palette = QtWidgets.QVBoxLayout()
    palette.addWidget(QtWidgets.QLabel("GATE LIBRARY"))
    for gate in gate_arity:
        palette.addWidget(GateButton(gate))
    palette.addStretch(1)
    canvas = CircuitCanvas()
    content.addLayout(palette)

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
        state_visualizer.set_measurements = lambda counts: None
    tabs.addTab(state_visualizer, "State Visualizer")
    content.addWidget(tabs, 1)
    outer.addLayout(content, 1)
    outer.addWidget(status_label)

    root._workers = []

    def launch_simulation():
        if any(worker.isRunning() for worker in root._workers):
            status_label.setText("A simulation is already running.")
            return
        try:
            circuit = canvas.to_circuit()
        except Exception as exc:
            status_label.setText(f"Circuit validation failed: {exc}")
            return
        worker = SimulationWorker(
            backend_combo.currentData(), circuit, shots_input.value(), 7
        )
        run_button.setEnabled(False)
        status_label.setText(f"Running on {backend_combo.currentText()}…")

        def show_result(result):
            run_button.setEnabled(True)
            if result.statevector is not None:
                state_visualizer.set_statevector(result.statevector)
            elif result.counts:
                state_visualizer.set_measurements(result.counts)
            tabs.setCurrentWidget(state_visualizer)
            duration = result.execution_time_ms
            duration_text = f"{duration:.2f} ms" if duration is not None else "time unavailable"
            shot_text = str(result.shots) if result.shots is not None else "statevector"
            status_label.setText(
                f"{result.backend} {result.status} · {duration_text} · {shot_text}"
            )

        def show_error(message):
            run_button.setEnabled(True)
            status_label.setText(f"Simulation failed: {message}")

        worker.result_ready.connect(show_result)
        worker.failed.connect(show_error)
        worker.finished.connect(
            lambda w=worker: root._workers.remove(w) if w in root._workers else None
        )
        root._workers.append(worker)
        worker.start()

    run_button.clicked.connect(launch_simulation)
    root.canvas = canvas
    root.to_circuit = canvas.to_circuit
    root.state_visualizer = state_visualizer
    root.set_statevector = state_visualizer.set_statevector
    root.run_button = run_button
    root.backend_combo = backend_combo
    root.status_label = status_label
    root.run_simulation = launch_simulation
    return root
