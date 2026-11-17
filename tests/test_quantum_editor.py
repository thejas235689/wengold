def test_quantum_editor_builds_offscreen(qtbot):
    from PyQt6 import QtWidgets
    from quantum.ui.circuit_editor import build_editor

    widget = build_editor(QtWidgets)
    qtbot.addWidget(widget)
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
