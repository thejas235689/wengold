def test_quantum_editor_builds_offscreen(qtbot):
    from PyQt6 import QtWidgets
    from quantum.ui.circuit_editor import build_editor
    widget = build_editor(QtWidgets)
    qtbot.addWidget(widget)
    assert widget.isWidgetType()
    assert widget.findChild(QtWidgets.QGraphicsView) is not None
