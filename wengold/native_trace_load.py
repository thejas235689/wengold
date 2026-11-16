"""Keep optional FST decoding off the Qt event loop."""
from __future__ import annotations

from queue import Empty, SimpleQueue
from threading import Thread


def load_paths(owner, QtCore, paths, read, callback):
    def operation():
        try:
            return [read(path) for path in paths], None
        except Exception as exc:
            return None, str(exc)

    if not any(path.lower().endswith(".fst") for path in paths):
        callback(*operation())
        return

    results = SimpleQueue()
    timer = QtCore.QTimer(owner)

    def poll():
        try:
            result = results.get_nowait()
        except Empty:
            return
        timer.stop()
        timer.deleteLater()
        callback(*result)

    timer.timeout.connect(poll)
    Thread(target=lambda: results.put(operation()), name="wengold-fst-load", daemon=True).start()
    timer.start(25)
