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
    assert widget.run_button.text() == "Run simulation"
    assert widget.debug_button.text() == "Build debug trace"
    assert widget.amplitude_table.columnCount() == 6
    assert widget.amplitude_table.objectName() == "quantumAmplitudeTable"
    assert widget.backend_combo.count() == 3
    assert callable(widget.run_simulation)
    assert callable(widget.run_debug_trace)
    assert widget.debug_slider.minimum() == 0
    assert widget.debug_slider.maximum() == 0
    assert not widget.debug_slider.isEnabled()
    assert not widget.debug_previous_button.isEnabled()
    assert not widget.debug_next_button.isEnabled()

    widget.canvas.operations.extend([
        {"id": "h0", "gate": "H", "qubits": [0], "column": 0},
        {"id": "cx01", "gate": "CNOT", "qubits": [0, 1], "column": 1},
    ])
    circuit = widget.to_circuit()
    assert [operation.gate for operation in circuit.operations] == ["H", "CNOT"]
    assert circuit.operations[1].controls == (0,)
    assert circuit.operations[1].targets == (1,)
    widget.canvas.operations.append(
        {"id": "cswap012", "gate": "CSWAP", "qubits": [0, 1, 2], "column": 2}
    )
    cswap = widget.to_circuit().operations[-1]
    assert cswap.controls == (0,)
    assert cswap.targets == (1, 2)

    widget.canvas.set_debug_operation("h0")
    assert widget.canvas.debug_operation_id == "h0"
    widget.canvas.set_debug_operation(None)
    widget.close()
    app.processEvents()
