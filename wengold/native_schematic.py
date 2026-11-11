"""Native interactive netlist connectivity canvas, powered only by Yosys JSON.

Horizontal tiers show derived intercell connections. No placement, timing,
cell geometry or routes are inferred from this schematic.
"""
from __future__ import annotations

from collections import defaultdict


def make_schematic_canvas(QtCore, QtGui, QtWidgets):
    view = QtWidgets.QGraphicsView()
    view.setObjectName("implSchematicCanvas")
    scene = QtWidgets.QGraphicsScene(view)
    view.setScene(scene)
    view.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    view.setDragMode(QtWidgets.QGraphicsView.DragMode.ScrollHandDrag)
    view.setTransformationAnchor(QtWidgets.QGraphicsView.ViewportAnchor.AnchorUnderMouse)
    view.setBackgroundBrush(QtGui.QBrush(QtGui.QColor("#FFFEF8")))

    def render(graph):
        scene.clear()
        cells = graph.get("cells", [])
        edges = graph.get("edges", [])
        if not cells:
            scene.addText("No synthesized cell connections available.")
            return
        names = {cell["id"] for cell in cells}
        adjacency = defaultdict(list)
        indegree = {name: 0 for name in names}
        for edge in edges:
            src, dst = edge["from"], edge["to"]
            if src in names and dst in names and src != dst:
                adjacency[src].append(dst)
                indegree[dst] += 1
        levels = {name: 0 for name in names}
        # Bounded relaxation; feedback paths are drawn at the last level reached.
        for _ in range(min(12, len(names))):
            changed = False
            for src, destinations in adjacency.items():
                for dst in destinations:
                    if levels[dst] <= levels[src] and levels[src] < 11:
                        levels[dst] = levels[src] + 1
                        changed = True
            if not changed:
                break
        positions = {}
        by_level = defaultdict(list)
        for cell in cells:
            by_level[levels[cell["id"]]].append(cell)
        for level, group in sorted(by_level.items()):
            for row, cell in enumerate(group):
                x, y = 25 + level * 235, 30 + row * 98
                positions[cell["id"]] = (x, y)
        edge_pen = QtGui.QPen(QtGui.QColor("#8598AB"), 1.4)
        for edge in edges:
            a, b = positions.get(edge["from"]), positions.get(edge["to"])
            if a is None or b is None:
                continue
            x1, y1 = a[0] + 188, a[1] + 28
            x2, y2 = b[0], b[1] + 28
            mid = (x1 + x2) / 2
            path = QtGui.QPainterPath(QtCore.QPointF(x1, y1))
            path.lineTo(mid, y1)
            path.lineTo(mid, y2)
            path.lineTo(x2, y2)
            scene.addPath(path, edge_pen)
        for cell in cells:
            x, y = positions[cell["id"]]
            rounded = QtGui.QPainterPath()
            rounded.addRoundedRect(QtCore.QRectF(x, y, 188, 58), 7, 7)
            shape = scene.addPath(
                rounded, QtGui.QPen(QtGui.QColor("#B09C58"), 1.5),
                QtGui.QBrush(QtGui.QColor("#FFF0AD")))
            shape.setToolTip(cell["id"] + "\n" + cell["type"])
            typ = scene.addText(cell["type"][:29])
            typ.setDefaultTextColor(QtGui.QColor("#46380D"))
            typ.setPos(x + 6, y + 5)
            name = scene.addText(cell["id"][:27])
            name.setDefaultTextColor(QtGui.QColor("#695820"))
            name.setPos(x + 6, y + 28)
        caption = scene.addText(
            graph.get("module", "") + "  — Yosys synthesized connectivity; NOT physical layout"
            + ("  [view truncated]" if graph.get("truncated") else ""))
        caption.setDefaultTextColor(QtGui.QColor("#4A6370"))
        caption.setPos(25, 0)
        scene.setSceneRect(scene.itemsBoundingRect().adjusted(-20, -20, 60, 60))
        view.resetTransform()
        view.scale(0.85, 0.85)

    def zoom(factor):
        view.scale(factor, factor)

    view.showSchematic = render
    view.zoomSchematic = zoom
    return view
