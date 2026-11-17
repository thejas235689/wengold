"""Standalone WENGOLD Quantum Designer launcher."""
from __future__ import annotations
import sys

def main(argv=None):
    try:
        from PyQt6 import QtWidgets
    except ImportError:
        print("Quantum Designer needs PyQt6. Install with: pip install 'wengold[native,quantum]'",file=sys.stderr)
        return 2
    from quantum.ui.circuit_editor import build_editor
    app=QtWidgets.QApplication(argv or sys.argv)
    window=QtWidgets.QMainWindow(); window.setWindowTitle("WENGOLD — Quantum Designer")
    window.resize(1180,760); window.setCentralWidget(build_editor(QtWidgets))
    window.show(); return app.exec()

if __name__=="__main__": raise SystemExit(main())
