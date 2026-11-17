import pytest


def test_quantum_editor_builds_offscreen():
    pytest.importorskip("PyQt6")
    from PyQt6 import QtWidgets
    from quantum.ui.circuit_editor import build_editor

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    widget = build_editor(QtWidgets)
    assert widget.isWidgetType()
    assert widget.findChild(QtWidgets.QGraphicsView) is not None
    assert widget.to_circuit().num_qubits == 3

    widget.canvas.operations.extend([
        {"id": "h0", "gate": "H", "qubits": [0], "column": 0},
        {"id": "cx01", "gate": "CNOT", "qubits": [0, 1], "column": 1},
    ])
    circuit = widget.to_circuit()
    assert [operation.gate for operation in circuit.operations] == ["H", "CNOT"]
    assert circuit.operations[1].controls == (0,)
    assert circuit.operations[1].targets == (1,)
    widget.close()
    app.processEvents()
