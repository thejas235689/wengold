"""Minimal native drag-and-drop circuit editor foundation for PyQt6."""
from __future__ import annotations

def build_editor(QtWidgets):
    class GateButton(QtWidgets.QPushButton):
        def __init__(self, gate, parent=None):
            super().__init__(gate,parent); self.gate=gate
        def mouseMoveEvent(self,event):
            if event.buttons() & __import__("PyQt6").QtCore.Qt.MouseButton.LeftButton:
                mime=__import__("PyQt6").QtCore.QMimeData(); mime.setText(self.gate)
                drag=__import__("PyQt6").QtGui.QDrag(self); drag.setMimeData(mime); drag.exec()
            super().mouseMoveEvent(event)
    class CircuitCanvas(QtWidgets.QGraphicsView):
        def __init__(self,parent=None):
            self.scene=QtWidgets.QGraphicsScene(parent); super().__init__(self.scene,parent)
            self.setAcceptDrops(True); self.num_qubits=3; self.operations=[]
            self.setMinimumSize(650,320); self.render_circuit()
        def dragEnterEvent(self,event):
            if event.mimeData().hasText(): event.acceptProposedAction()
        def dragMoveEvent(self,event): event.acceptProposedAction()
        def dropEvent(self,event):
            gate=event.mimeData().text().upper(); point=self.mapToScene(event.position().toPoint())
            q=max(0,min(self.num_qubits-1,round((point.y()-45)/75)))
            self.operations.append({"gate":gate,"qubit":q,"column":max(0,round((point.x()-100)/95))})
            self.render_circuit(); event.acceptProposedAction()
        def render_circuit(self):
            self.scene.clear()
            for q in range(self.num_qubits):
                y=45+q*75; self.scene.addText(f"q[{q}]").setPos(8,y-13)
                self.scene.addLine(65,y,900,y)
            for op in self.operations:
                x=100+op["column"]*95; y=45+op["qubit"]*75
                item=self.scene.addRect(x-24,y-19,48,38); item.setToolTip(op["gate"])
                self.scene.addText(op["gate"]).setPos(x-18,y-12)
    root=QtWidgets.QWidget(); layout=QtWidgets.QHBoxLayout(root)
    palette=QtWidgets.QVBoxLayout(); palette.addWidget(QtWidgets.QLabel("GATE LIBRARY"))
    for gate in ["H","X","Y","Z","S","T","RX","RY","RZ","CNOT","CZ","SWAP","MEASURE"]:
        palette.addWidget(GateButton(gate))
    palette.addStretch(1); canvas=CircuitCanvas()
    layout.addLayout(palette); layout.addWidget(canvas,1)
    return root
