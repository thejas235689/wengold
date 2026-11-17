"""Advanced native wave-debug panel: separate DUT RTL from TB/UVM observations.

All findings are deterministic rules over actual VCD samples. The opt-in local
LLM explains the evidence in a worker thread and cannot sign off a cause.
"""
from __future__ import annotations

import json
import os

from .wave_debug import diagnose, explain_with_local_ai
from .axi4_telemetry import decode_axi4
from .otel_telemetry import (build_otlp_bundle, write_otlp_bundle,
                             send_dynatrace_otlp)


def make_wave_debug(QtCore, QtGui, QtWidgets, project_root, on_crossprobe=None,
                    on_select_time=None, on_source_probe=None):
    page = QtWidgets.QWidget()
    page.setObjectName("advancedWaveDebug")
    layout = QtWidgets.QVBoxLayout(page)
    layout.setContentsMargins(9, 9, 9, 9)
    layout.setSpacing(7)
    roots = QtWidgets.QHBoxLayout()
    dut = QtWidgets.QLineEdit("tb.dut")
    dut.setObjectName("waveDutScopes")
    dut.setPlaceholderText("DUT hierarchy roots: tb.dut, tb.u_dut")
    tb = QtWidgets.QLineEdit("tb")
    tb.setObjectName("waveTbScopes")
    tb.setPlaceholderText("TB/UVM hierarchy roots: tb")
    window = QtWidgets.QSpinBox()
    window.setRange(1, 256)
    window.setValue(6)
    window.setObjectName("waveHandshakeWindow")
    run = QtWidgets.QPushButton("Analyze VCD evidence")
    run.setObjectName("waveAnalyze")
    for w in (QtWidgets.QLabel("RTL / DUT"), dut, QtWidgets.QLabel("TB / UVM"), tb,
              QtWidgets.QLabel("Handshake samples"), window, run):
        roots.addWidget(w)
    layout.addLayout(roots)

    # Differential PASS-vs-FAIL waveform comparison. The primary waveform is
    # the loaded capture; a second VCD is explicitly selected as the failing run.
    diff_row = QtWidgets.QHBoxLayout()
    pass_path = QtWidgets.QLineEdit()
    pass_path.setObjectName("wavePassVcdPath")
    pass_path.setPlaceholderText("PASS VCD (known-good reference)")
    fail_path = QtWidgets.QLineEdit()
    fail_path.setObjectName("waveFailVcdPath")
    fail_path.setPlaceholderText("FAIL VCD (failing regression)")
    pass_browse = QtWidgets.QPushButton("Browse PASS…")
    pass_browse.setObjectName("waveBrowsePassVcd")
    fail_browse = QtWidgets.QPushButton("Browse FAIL…")
    fail_browse.setObjectName("waveBrowseFailVcd")
    compare_button = QtWidgets.QPushButton("Compare PASS vs FAIL")
    compare_button.setObjectName("waveComparePassFail")
    compare_button.setEnabled(True)
    diff_row.addWidget(pass_path, 2)
    diff_row.addWidget(pass_browse)
    diff_row.addWidget(fail_path, 2)
    diff_row.addWidget(fail_browse)
    diff_row.addWidget(compare_button)
    layout.addLayout(diff_row)
    align_row = QtWidgets.QHBoxLayout()
    alignment_mode = QtWidgets.QComboBox()
    alignment_mode.setObjectName("waveDiffAlignment")
    alignment_mode.addItem("Absolute simulation time", "absolute")
    alignment_mode.addItem("Align at reset release", "reset")
    alignment_mode.addItem("Align by clock cycle + phase", "clock")
    pass_reset = QtWidgets.QLineEdit()
    pass_reset.setObjectName("waveDiffPassReset")
    pass_reset.setPlaceholderText("PASS reset path, e.g. tb.rst_n")
    fail_reset = QtWidgets.QLineEdit()
    fail_reset.setObjectName("waveDiffFailReset")
    fail_reset.setPlaceholderText("FAIL reset path (blank = PASS path)")
    reset_active = QtWidgets.QComboBox()
    reset_active.setObjectName("waveDiffResetActive")
    reset_active.addItem("Reset active LOW", 0)
    reset_active.addItem("Reset active HIGH", 1)
    pass_clock = QtWidgets.QLineEdit()
    pass_clock.setObjectName("waveDiffPassClock")
    pass_clock.setPlaceholderText("PASS clock path (blank = detected)")
    fail_clock = QtWidgets.QLineEdit()
    fail_clock.setObjectName("waveDiffFailClock")
    fail_clock.setPlaceholderText("FAIL clock path (blank = PASS path)")
    for widget in (alignment_mode, pass_reset, fail_reset, reset_active,
                   pass_clock, fail_clock):
        align_row.addWidget(widget)
    layout.addLayout(align_row)
    diff_summary = QtWidgets.QLabel("Differential comparison not run")
    diff_summary.setObjectName("waveDiffSummary")
    layout.addWidget(diff_summary)
    diff_table = QtWidgets.QTableWidget(0, 5)
    diff_table.setObjectName("waveDiffSignals")
    diff_table.setHorizontalHeaderLabels(
        ["Signal", "Differences", "First aligned time", "PASS value", "FAIL value"])
    diff_table.horizontalHeader().setStretchLastSection(True)
    diff_table.setMaximumHeight(155)
    diff_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
    layout.addWidget(diff_table)
    diff_timeline = QtWidgets.QTableWidget(0, 5)
    diff_timeline.setObjectName("waveDiffTimeline")
    diff_timeline.setHorizontalHeaderLabels(
        ["Aligned time / cycle", "Signal", "PASS value", "FAIL value", "Difference type"])
    diff_timeline.horizontalHeader().setStretchLastSection(True)
    diff_timeline.setMaximumHeight(175)
    diff_timeline.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
    layout.addWidget(diff_timeline)
    diff_state = {"report": None, "pass_wave": None, "fail_wave": None}

    # Live schematic context for waveform and protocol debugging.  The diagram
    # is intentionally structural: only the alert/status is derived from trace
    # evidence; it never infers connectivity from signal-name similarity.
    schematic_group = QtWidgets.QGroupBox("Schematic View — AXI data path")
    schematic_group.setObjectName("waveSchematicGroup")
    schematic_layout = QtWidgets.QVBoxLayout(schematic_group)
    schematic_alert = QtWidgets.QLabel("No divergence selected — schematic is a structural view")
    schematic_alert.setObjectName("waveSchematicAlert")
    schematic_alert.setWordWrap(True)
    schematic_layout.addWidget(schematic_alert)
    schematic_scene = QtWidgets.QGraphicsScene(page)
    schematic_view = QtWidgets.QGraphicsView(schematic_scene)
    schematic_view.setObjectName("waveSchematicView")
    schematic_view.setMinimumHeight(205)
    schematic_view.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    schematic_view.setDragMode(QtWidgets.QGraphicsView.DragMode.ScrollHandDrag)
    schematic_layout.addWidget(schematic_view)
    schematic_scene.setSceneRect(0, 0, 760, 190)

    def schematic_node(x, y, width, height, title, detail, fill):
        rounded = QtGui.QPainterPath()
        rounded.addRoundedRect(QtCore.QRectF(x, y, width, height), 9, 9)
        rect = schematic_scene.addPath(
            rounded, QtGui.QPen(QtGui.QColor("#38bdf8"), 2),
            QtGui.QBrush(QtGui.QColor(fill)))
        rect.setToolTip(title + "\n" + detail)
        text_item = schematic_scene.addText(title + "\n" + detail)
        text_item.setDefaultTextColor(QtGui.QColor("#f8fafc"))
        text_item.setFont(QtGui.QFont("Sans Serif", 9, QtGui.QFont.Weight.DemiBold))
        text_item.setTextWidth(width - 16)
        text_item.setPos(x + 8, y + 10)
        return rect

    def schematic_link(x1, y1, x2, y2, label, color="#94a3b8"):
        pen = QtGui.QPen(QtGui.QColor(color), 2)
        schematic_scene.addLine(x1, y1, x2, y2, pen)
        label_item = schematic_scene.addText(label)
        label_item.setDefaultTextColor(QtGui.QColor(color))
        label_item.setFont(QtGui.QFont("Sans Serif", 8))
        label_item.setPos((x1 + x2) / 2 - 24, (y1 + y2) / 2 - 18)

    def update_schematic(alert=None, severity="info"):
        schematic_scene.clear()
        schematic_node(18, 55, 145, 82, "AXI Master", "AW / W / B\nAR / R channels", "#17365d")
        schematic_node(245, 55, 165, 82, "AXI Slave Interface", "Handshake + ID routing", "#123b68")
        schematic_node(505, 15, 190, 65, "Memory Controller", "Address decode + access", "#14532d")
        schematic_node(505, 112, 190, 65, "Response Logic", "BRESP / RRESP generation", "#4c1d95")
        schematic_link(163, 76, 245, 76, "AW / W / AR")
        schematic_link(245, 118, 163, 118, "B / R", "#22c55e")
        schematic_link(410, 76, 505, 48, "Address / data")
        schematic_link(505, 144, 410, 111, "Response", "#c084fc")
        schematic_link(600, 80, 600, 112, "status", "#f59e0b")
        if alert:
            color = "#ef4444" if severity == "error" else "#f59e0b"
            alert_item = schematic_scene.addText("! " + alert)
            alert_item.setDefaultTextColor(QtGui.QColor(color))
            alert_item.setFont(QtGui.QFont("Sans Serif", 9, QtGui.QFont.Weight.Bold))
            alert_item.setPos(18, 5)
            schematic_alert.setText(alert)
            schematic_alert.setStyleSheet(
                "color: " + color + "; font-weight: 700; padding: 4px;")
        else:
            schematic_alert.setText("No protocol failure identified from current evidence.")
            schematic_alert.setStyleSheet("color: #94a3b8; padding: 4px;")
        schematic_view.fitInView(schematic_scene.sceneRect(),
                                 QtCore.Qt.AspectRatioMode.KeepAspectRatio)

    update_schematic()
    layout.addWidget(schematic_group)

    # RTL-derived hierarchy view. The graph is generated from Yosys JSON and
    # uses actual elaborated instance port connections, not guessed signal names.
    hierarchy_group = QtWidgets.QGroupBox("RTL Hierarchy — Yosys elaboration")
    hierarchy_group.setObjectName("waveRtlHierarchyGroup")
    hierarchy_layout = QtWidgets.QVBoxLayout(hierarchy_group)
    hierarchy_controls = QtWidgets.QHBoxLayout()
    hierarchy_top = QtWidgets.QLineEdit()
    hierarchy_top.setObjectName("waveHierarchyTop")
    hierarchy_top.setPlaceholderText("Top module name (required)")
    hierarchy_yosys = QtWidgets.QLineEdit("yosys")
    hierarchy_yosys.setObjectName("waveHierarchyYosys")
    hierarchy_yosys.setMaximumWidth(150)
    hierarchy_frontend = QtWidgets.QComboBox()
    hierarchy_frontend.setObjectName("waveHierarchyFrontend")
    hierarchy_frontend.addItem("Slang + Yosys (SV-2017)", "slang")
    hierarchy_frontend.addItem("Yosys built-in SV subset", "yosys")
    hierarchy_wave_prefix = QtWidgets.QLineEdit()
    hierarchy_wave_prefix.setObjectName("waveHierarchyWavePrefix")
    hierarchy_wave_prefix.setPlaceholderText("VCD root prefix, e.g. tb.dut (optional)")
    hierarchy_build = QtWidgets.QPushButton("Elaborate RTL hierarchy")
    hierarchy_build.setObjectName("waveBuildRtlHierarchy")
    hierarchy_controls.addWidget(QtWidgets.QLabel("Top"))
    hierarchy_controls.addWidget(hierarchy_top, 2)
    hierarchy_controls.addWidget(QtWidgets.QLabel("Yosys"))
    hierarchy_controls.addWidget(hierarchy_yosys)
    hierarchy_controls.addWidget(hierarchy_frontend)
    hierarchy_controls.addWidget(hierarchy_wave_prefix, 2)
    hierarchy_controls.addWidget(hierarchy_build)
    hierarchy_layout.addLayout(hierarchy_controls)
    hierarchy_status = QtWidgets.QLabel(
        "Slang mode requires the yosys-slang plugin (OSS CAD Suite). "
        "For the RISC-V project, the RTL source list is read from sim/run.py.")
    hierarchy_status.setObjectName("waveHierarchyStatus")
    hierarchy_status.setWordWrap(True)
    hierarchy_layout.addWidget(hierarchy_status)
    hierarchy_split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
    hierarchy_tree = QtWidgets.QTreeWidget()
    hierarchy_tree.setObjectName("waveHierarchyTree")
    hierarchy_tree.setHeaderLabels(["Instance / port", "Direction / width"])
    hierarchy_detail = QtWidgets.QPlainTextEdit()
    hierarchy_detail.setObjectName("waveHierarchyDetail")
    hierarchy_detail.setReadOnly(True)
    hierarchy_detail.setMaximumHeight(150)
    hierarchy_split.addWidget(hierarchy_tree)
    hierarchy_split.addWidget(hierarchy_detail)
    hierarchy_layout.addWidget(hierarchy_split)
    hierarchy_scene = QtWidgets.QGraphicsScene(page)
    hierarchy_canvas = QtWidgets.QGraphicsView(hierarchy_scene)
    hierarchy_canvas.setObjectName("waveHierarchyCanvas")
    hierarchy_canvas.setMinimumHeight(230)
    hierarchy_canvas.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    hierarchy_canvas.setDragMode(QtWidgets.QGraphicsView.DragMode.ScrollHandDrag)
    hierarchy_layout.addWidget(hierarchy_canvas)
    hierarchy_state = {"graph": None, "nodes": {}}

    def render_rtl_hierarchy(graph):
        hierarchy_scene.clear()
        nodes = graph.get("nodes", [])
        edges = graph.get("edges", [])
        if not nodes:
            hierarchy_scene.addText("No RTL module instances were found.")
            return
        children = {}
        for node in nodes:
            parent = node["id"].rsplit(".", 1)[0] if "." in node["id"] else ""
            children.setdefault(parent, []).append(node)
        positions = {}
        depth_groups = {}
        for node in nodes:
            depth = node["id"].count(".")
            depth_groups.setdefault(depth, []).append(node)
        for depth, group in sorted(depth_groups.items()):
            for row, node in enumerate(group):
                positions[node["id"]] = (24 + depth * 250, 36 + row * 100)
        for edge in edges:
            src_path = edge["from"].rsplit(".", 1)[0]
            dst_path = edge["instance"]
            a, b = positions.get(src_path), positions.get(dst_path)
            if a and b:
                x1, y1 = a[0] + 205, a[1] + 32
                x2, y2 = b[0], b[1] + 32
                path = QtGui.QPainterPath(QtCore.QPointF(x1, y1))
                path.lineTo((x1 + x2) / 2, y1)
                path.lineTo((x1 + x2) / 2, y2)
                path.lineTo(x2, y2)
                hierarchy_scene.addPath(path, QtGui.QPen(QtGui.QColor("#8A9AA8"), 1.2))
        for node in nodes:
            x, y = positions[node["id"]]
            rounded = QtGui.QPainterPath()
            rounded.addRoundedRect(QtCore.QRectF(x, y, 205, 64), 8, 8)
            rect = hierarchy_scene.addPath(
                rounded, QtGui.QPen(QtGui.QColor("#B09C58"), 1.5),
                QtGui.QBrush(QtGui.QColor("#FFF0AD")))
            rect.setToolTip(node["id"] + "\\n" + node["module"])
            title = hierarchy_scene.addText(node["module"])
            title.setDefaultTextColor(QtGui.QColor("#46380D"))
            title.setPos(x + 8, y + 5)
            inst = hierarchy_scene.addText(node["id"])
            inst.setDefaultTextColor(QtGui.QColor("#695820"))
            inst.setPos(x + 8, y + 31)
        caption = hierarchy_scene.addText(
            f"Yosys elaborated hierarchy · {graph['instance_count']} instances · "
            f"{graph['connection_count']} port-bit connections · not physical layout")
        caption.setDefaultTextColor(QtGui.QColor("#4A6370"))
        caption.setPos(24, 5)
        hierarchy_scene.setSceneRect(hierarchy_scene.itemsBoundingRect().adjusted(-15, -15, 30, 30))
        hierarchy_canvas.fitInView(hierarchy_scene.sceneRect(),
                                   QtCore.Qt.AspectRatioMode.KeepAspectRatio)

    def build_rtl_hierarchy():
        from pathlib import Path
        from .rtl_hierarchy import elaborate_with_yosys
        root = Path(project_root).resolve()
        from .rtl_hierarchy import load_riscv_core_sources
        if (root / "sim" / "run.py").is_file() and (root / "rtl" / "riscv_core_top.sv").is_file():
            source_names = load_riscv_core_sources(root)
            sources = [root / name for name in source_names]
            if not hierarchy_top.text().strip():
                hierarchy_top.setText("riscv_core_top")
        else:
            sources = sorted(
                path for path in root.rglob("*")
                if path.is_file() and path.suffix.lower() in {".sv", ".v"}
                and not any(part in {".git", ".venv", "venv", "build", "dist", "__pycache__"}
                            for part in path.parts)
            )
        if not hierarchy_top.text().strip():
            hierarchy_status.setText("Enter the exact top module name before elaboration.")
            return
        hierarchy_build.setEnabled(False)
        frontend = hierarchy_frontend.currentData()
        hierarchy_status.setText(
            f"Running {frontend} elaboration on {len(sources)} source files…")
        try:
            graph = elaborate_with_yosys(
                root, sources, top=hierarchy_top.text().strip(),
                yosys=hierarchy_yosys.text().strip() or "yosys",
                frontend=frontend)
            hierarchy_state["graph"] = graph
            hierarchy_state["nodes"] = {node["id"]: node for node in graph["nodes"]}
            hierarchy_tree.clear()
            items = {}
            for node in graph["nodes"]:
                parent_path = node["id"].rsplit(".", 1)[0] if "." in node["id"] else ""
                parent_item = items.get(parent_path)
                item = QtWidgets.QTreeWidgetItem(
                    [node["id"], node["module"]])
                item.setData(0, QtCore.Qt.ItemDataRole.UserRole, node["id"])
                if parent_item is not None:
                    parent_item.addChild(item)
                else:
                    hierarchy_tree.addTopLevelItem(item)
                items[node["id"]] = item
                for port in node.get("ports", []):
                    port_item = QtWidgets.QTreeWidgetItem(
                        [port["name"], f"{port['direction']} · {port['width']} bit(s)"])
                    port_item.setData(0, QtCore.Qt.ItemDataRole.UserRole,
                                      node["id"] + "." + port["name"])
                    port_item.setData(1, QtCore.Qt.ItemDataRole.UserRole, port)
                    item.addChild(port_item)
            hierarchy_tree.expandToDepth(1)
            render_rtl_hierarchy(graph)
            note = " · truncated at safety limit" if graph.get("truncated") else ""
            hierarchy_status.setText(
                f"Yosys hierarchy ready: {graph['instance_count']} instances, "
                f"{graph['connection_count']} actual port-bit connections{note}. "
                f"Frontend: {graph.get('frontend', frontend)}. "
                "Select a port to cross-probe the waveform and RTL.")
        except Exception as exc:
            hierarchy_status.setText("RTL hierarchy elaboration failed: " + str(exc))
        finally:
            hierarchy_build.setEnabled(True)

    def select_hierarchy_item(item, _column):
        signal_path = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
        port = item.data(1, QtCore.Qt.ItemDataRole.UserRole)
        node_path = signal_path.rsplit(".", 1)[0] if port else signal_path
        node = hierarchy_state["nodes"].get(node_path, {})
        source = node.get("source") or (port or {}).get("source")
        hierarchy_detail.setPlainText(json.dumps({
            "selected": signal_path,
            "port": port,
            "instance": node,
            "source_location": source,
            "cross_probe_note": (
                "The full hierarchical port path is sent to the waveform/source cross-probe. "
                "A source line is shown only when Yosys emitted a src attribute.")
        }, indent=2))
        wave_prefix = hierarchy_wave_prefix.text().strip().strip(".")
        graph = hierarchy_state.get("graph") or {}
        top_name = graph.get("top", "")
        if wave_prefix and top_name and signal_path.startswith(top_name + "."):
            signal_path = wave_prefix + "." + signal_path[len(top_name) + 1:]
        elif wave_prefix and signal_path == top_name:
            signal_path = wave_prefix
        if port and on_crossprobe:
            on_crossprobe(signal_path)
        elif node.get("ports") and on_crossprobe:
            on_crossprobe(wave_prefix + "." + node_path + "." +
                          node["ports"][0]["name"] if wave_prefix else
                          node_path + "." + node["ports"][0]["name"])
        if source and source.get("file"):
            hierarchy_status.setText(
                f"Source: {source['file']}:{source['line']}:{source.get('column', 1)} · "
                "select a port to cross-probe its full hierarchical signal path.")
            if on_source_probe:
                on_source_probe(source)

    hierarchy_build.clicked.connect(build_rtl_hierarchy)
    hierarchy_tree.itemClicked.connect(select_hierarchy_item)
    hierarchy_layout.addWidget(QtWidgets.QLabel(
        "Port cross-probe uses elaborated instance paths; source locations depend on Yosys src metadata."))
    layout.addWidget(hierarchy_group)

    def browse_vcd(field, caption):
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(
            page, caption, "", "VCD waveform (*.vcd);;All files (*)")
        if filename:
            field.setText(filename)

    pass_browse.clicked.connect(lambda: browse_vcd(pass_path, "Select passing VCD"))
    fail_browse.clicked.connect(lambda: browse_vcd(fail_path, "Select failing VCD"))

    def compare_pass_fail():
        from pathlib import Path
        from .wave import parse_vcd
        from .wave_diff import compare_waveforms
        pfile, ffile = pass_path.text().strip(), fail_path.text().strip()
        if not pfile or not ffile:
            diff_summary.setText("Select both a PASS VCD and a FAIL VCD.")
            return
        try:
            p_wave = parse_vcd(Path(pfile).read_text(errors="replace"))
            f_wave = parse_vcd(Path(ffile).read_text(errors="replace"))
            mode = alignment_mode.currentData()
            options = {"alignment": mode}
            if mode == "reset":
                options.update({
                    "pass_reset_signal": pass_reset.text().strip(),
                    "fail_reset_signal": fail_reset.text().strip() or pass_reset.text().strip(),
                    "reset_active_level": reset_active.currentData()})
            elif mode == "clock":
                options.update({
                    "pass_clock_signal": pass_clock.text().strip() or None,
                    "fail_clock_signal": fail_clock.text().strip() or pass_clock.text().strip() or None})
            report = compare_waveforms(p_wave, f_wave, **options)
        except (OSError, ValueError, TypeError) as exc:
            diff_summary.setText("Waveform comparison failed: " + str(exc))
            diff_table.setRowCount(0)
            diff_timeline.setRowCount(0)
            return
        diff_state.update(report=report, pass_wave=p_wave, fail_wave=f_wave)
        if report.get("first_divergence"):
            first_item = report["first_divergence"]
            is_response_error = ("bresp" in first_item["signal"].lower()
                                 or "rresp" in first_item["signal"].lower()
                                 or "slverr" in str(first_item["fail"]).lower()
                                 or "decerr" in str(first_item["fail"]).lower())
            update_schematic(
                f"First divergence at {first_item['aligned_time']} {first_item['time_unit']}: "
                f"{first_item['signal']} PASS={first_item['pass']} FAIL={first_item['fail']}",
                "error" if is_response_error else "warning")
        else:
            update_schematic()
        diff_table.setRowCount(len(report["per_signal"]))
        for row, item in enumerate(report["per_signal"]):
            first = item["first_difference"]
            values = (item["signal"], item["differences"], first["aligned_time"],
                      first["pass"], first["fail"])
            for col, value in enumerate(values):
                diff_table.setItem(row, col, QtWidgets.QTableWidgetItem(str(value)))
        diff_timeline.setRowCount(len(report["differences"]))
        for row, item in enumerate(report["differences"]):
            label = f"{item['aligned_time']} {item['time_unit']}"
            values = (label, item["signal"], item["pass"], item["fail"], item["kind"])
            for col, value in enumerate(values):
                cell = QtWidgets.QTableWidgetItem(str(value))
                if item["kind"] == "unknown_vs_known":
                    cell.setBackground(QtGui.QColor("#704b20"))
                elif item["kind"] == "width_mismatch":
                    cell.setBackground(QtGui.QColor("#633b72"))
                else:
                    cell.setBackground(QtGui.QColor("#713b3b"))
                diff_timeline.setItem(row, col, cell)
        first = report["first_divergence"]
        if first:
            diff_summary.setText(
                f"FIRST DIVERGENCE: {first['signal']} at "
                f"{first['aligned_time']} {first['time_unit']} · "
                f"PASS={first['pass']} · FAIL={first['fail']} · "
                f"{report['total_differences']} differences across "
                f"{len(report['per_signal'])} signals · "
                f"{len(report['pass_only_signals'])} PASS-only / "
                f"{len(report['fail_only_signals'])} FAIL-only signals · "
                f"alignment={report['alignment']['mode']}")
        else:
            diff_summary.setText(
                f"No value differences on {report['common_signals']} common signals "
                f"over {report['compared_timestamps']} aligned timestamps "
                f"({report['alignment']['mode']} alignment). "
                f"PASS-only: {len(report['pass_only_signals'])}; "
                f"FAIL-only: {len(report['fail_only_signals'])}.")
        findings_detail.setPlainText(json.dumps(report, indent=2))

    def select_diff_signal():
        row = diff_table.currentRow()
        report = diff_state["report"]
        if report is None or row < 0 or row >= len(report["per_signal"]):
            return
        item = report["per_signal"][row]
        if on_crossprobe:
            on_crossprobe(item["signal"])
        # The currently loaded waveform remains the timeline reference. Jump
        # to its closest physical timestamp to the first divergence.
        if on_select_time and state["wave"] is not None:
            # Absolute-time cross-probing is exact. Reset/cycle-aligned overlays
            # intentionally avoid jumping to a misleading raw-time sample.
            if report["alignment"]["mode"] == "absolute":
                target = item["first_difference"]["aligned_time"]
                scale = state["wave"].get("time_unit_ns") or 1
                times = state["wave"].get("times", list(range(state["wave"].get("cycles", 0))))
                try:
                    from decimal import Decimal
                    target_tick = Decimal(target) / Decimal(str(scale))
                    index = min(range(len(times)), key=lambda i: abs(Decimal(str(times[i])) - target_tick))
                    on_select_time(index)
                except (ValueError, ZeroDivisionError):
                    pass
        findings_detail.setPlainText(json.dumps(item, indent=2))

    compare_button.clicked.connect(compare_pass_fail)
    diff_table.itemSelectionChanged.connect(select_diff_signal)

    axi_row = QtWidgets.QHBoxLayout()
    axi_prefix = QtWidgets.QLineEdit("tb.dut.axi")
    axi_prefix.setObjectName("waveAxi4Prefix")
    axi_prefix.setPlaceholderText("AXI4 interface prefix, for example tb.dut.m_axi")
    axi_clock = QtWidgets.QLineEdit()
    axi_clock.setObjectName("waveAxi4Clock")
    axi_clock.setPlaceholderText("ACLK full signal path (blank = interface ACLK, then waveform clock)")
    axi_stall_threshold = QtWidgets.QSpinBox()
    axi_stall_threshold.setObjectName("waveAxi4StallThreshold")
    axi_stall_threshold.setRange(1, 1000)
    axi_stall_threshold.setValue(8)
    axi_decode_button = QtWidgets.QPushButton("Decode AXI4 traffic")
    axi_decode_button.setObjectName("waveDecodeAxi4")
    axi_decode_button.setEnabled(False)
    axi_row.addWidget(QtWidgets.QLabel("AXI4 prefix"))
    axi_row.addWidget(axi_prefix, 2)
    axi_row.addWidget(axi_clock, 2)
    axi_row.addWidget(QtWidgets.QLabel("Stall cycles"))
    axi_row.addWidget(axi_stall_threshold)
    axi_row.addWidget(axi_decode_button)
    layout.addLayout(axi_row)

    views = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
    rtl_panel = QtWidgets.QWidget()
    rtl_layout = QtWidgets.QVBoxLayout(rtl_panel)
    rtl_title = QtWidgets.QLabel("DUT RTL — observed signals")
    rtl_layout.addWidget(rtl_title)
    rtl_table = QtWidgets.QTableWidget(0, 3)
    rtl_table.setObjectName("waveRtlSignals")
    rtl_table.setHorizontalHeaderLabels(["RTL signal", "Width", "Unknown samples"])
    rtl_table.horizontalHeader().setStretchLastSection(True)
    rtl_layout.addWidget(rtl_table)
    tb_panel = QtWidgets.QWidget()
    tb_layout = QtWidgets.QVBoxLayout(tb_panel)
    tb_layout.addWidget(QtWidgets.QLabel("Verification environment — observed signals"))
    tb_table = QtWidgets.QTableWidget(0, 3)
    tb_table.setObjectName("waveTbSignals")
    tb_table.setHorizontalHeaderLabels(["TB/UVM signal", "Width", "Unknown samples"])
    tb_table.horizontalHeader().setStretchLastSection(True)
    tb_layout.addWidget(tb_table)
    views.addWidget(rtl_panel)
    views.addWidget(tb_panel)
    layout.addWidget(views, 2)

    finding_table = QtWidgets.QTableWidget(0, 5)
    finding_table.setObjectName("waveRootCauseCandidates")
    finding_table.setHorizontalHeaderLabels(["Severity", "Domain", "Sample time", "Rule", "Observation"])
    finding_table.horizontalHeader().setStretchLastSection(True)
    finding_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
    layout.addWidget(finding_table, 2)

    traffic_summary = QtWidgets.QLabel("AXI4 decoder has not run")
    traffic_summary.setObjectName("waveAxi4Summary")
    layout.addWidget(traffic_summary)
    traffic_table = QtWidgets.QTableWidget(0, 7)
    traffic_table.setObjectName("waveAxi4Transactions")
    traffic_table.setHorizontalHeaderLabels(
        ["Direction", "ID", "Address", "Beats", "Response", "Status", "Start → End"])
    traffic_table.horizontalHeader().setStretchLastSection(True)
    traffic_table.setMaximumHeight(145)
    traffic_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
    layout.addWidget(traffic_table)

    findings_detail = QtWidgets.QPlainTextEdit()
    findings_detail.setObjectName("waveEvidenceDetail")
    findings_detail.setMaximumHeight(115)
    findings_detail.setReadOnly(True)
    layout.addWidget(findings_detail)

    otel_row = QtWidgets.QHBoxLayout()
    export_otel_button = QtWidgets.QPushButton("Export OpenTelemetry bundle")
    export_otel_button.setObjectName("waveExportOtel")
    export_otel_button.setEnabled(False)
    otel_hint = QtWidgets.QLabel("Offline OTLP-mapped JSON archive (not a Dynatrace upload)")
    otel_row.addWidget(export_otel_button)
    otel_row.addWidget(otel_hint, 1)
    layout.addLayout(otel_row)

    dynatrace_row = QtWidgets.QHBoxLayout()
    dynatrace_endpoint = QtWidgets.QLineEdit(
        os.environ.get("WENGOLD_DYNATRACE_OTLP_ENDPOINT", ""))
    dynatrace_endpoint.setObjectName("waveDynatraceEndpoint")
    dynatrace_endpoint.setPlaceholderText(
        "https://<environment-id>.live.dynatrace.com/api/v2/otlp")
    dynatrace_token = QtWidgets.QLineEdit(
        os.environ.get("WENGOLD_DYNATRACE_PLATFORM_TOKEN",
                   os.environ.get("WENGOLD_DYNATRACE_API_TOKEN", "")))
    dynatrace_token.setObjectName("waveDynatraceToken")
    dynatrace_token.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
    dynatrace_token.setPlaceholderText("Dynatrace platform token (openpipeline:traces/metrics/logs:ingest)")
    send_dynatrace_button = QtWidgets.QPushButton("Send via Dynatrace OTLP")
    send_dynatrace_button.setObjectName("waveSendDynatrace")
    send_dynatrace_button.setEnabled(False)
    dynatrace_row.addWidget(QtWidgets.QLabel("Dynatrace OTLP base"))
    dynatrace_row.addWidget(dynatrace_endpoint, 2)
    dynatrace_row.addWidget(dynatrace_token, 2)
    dynatrace_row.addWidget(send_dynatrace_button)
    layout.addLayout(dynatrace_row)

    ai_row = QtWidgets.QHBoxLayout()
    backend = QtWidgets.QComboBox()
    backend.addItems(["ollama", "openai"])
    backend.setObjectName("waveAiBackend")
    endpoint = QtWidgets.QLineEdit(os.environ.get("WENGOLD_LLM_URL", "http://127.0.0.1:11434"))
    endpoint.setObjectName("waveAiEndpoint")
    model = QtWidgets.QLineEdit(os.environ.get("WENGOLD_LLM_MODEL", "qwen2.5-coder:7b"))
    model.setObjectName("waveAiModel")
    explain = QtWidgets.QPushButton("Explain evidence using Local AI")
    explain.setObjectName("waveExplainAi")
    ai_row.addWidget(QtWidgets.QLabel("Local model"))
    ai_row.addWidget(backend)
    ai_row.addWidget(endpoint, 2)
    ai_row.addWidget(model)
    ai_row.addWidget(explain)
    layout.addLayout(ai_row)
    ai_text = QtWidgets.QPlainTextEdit()
    ai_text.setObjectName("waveAiRootCause")
    ai_text.setReadOnly(True)
    ai_text.setPlaceholderText("No AI output until you explicitly request local inference.")
    ai_text.setMaximumHeight(135)
    layout.addWidget(ai_text)
    state = {"wave": None, "report": None, "traffic": None, "display_findings": [], "busy": False, "otel_busy": False, "worker": None, "thread": None, "otel_worker": None, "otel_thread": None}
    page.debugState = state

    def update_table(table, group):
        table.setRowCount(len(group))
        for i, item in enumerate(group):
            for c, value in enumerate((item["name"], item["width"], item["unknown_samples"])):
                table.setItem(i, c, QtWidgets.QTableWidgetItem(str(value)))

    def chosen_roots(field):
        return tuple(x.strip() for x in field.text().split(",") if x.strip())

    def refresh_findings():
        base = list((state["report"] or {}).get("findings", []))
        traffic = list((state["traffic"] or {}).get("findings", []))
        rows = base + traffic
        state["display_findings"] = rows
        finding_table.setRowCount(len(rows))
        for i, finding in enumerate(rows):
            for c, value in enumerate((finding.get("severity", ""),
                                       finding.get("domain", ""),
                                       finding.get("time", ""),
                                       finding.get("rule", ""),
                                       finding.get("title", ""))):
                finding_table.setItem(i, c, QtWidgets.QTableWidgetItem(str(value)))
        return rows

    def telemetry_report_and_bundle():
        report = state["report"]
        wave_data = state["wave"]
        if report is None or wave_data is None:
            raise ValueError("Analyze a loaded waveform before exporting telemetry")
        combined = dict(report)
        combined["findings"] = list(report.get("findings", []))
        traffic = state["traffic"]
        transactions = []
        traffic_metrics = None
        if traffic is not None:
            combined["findings"].extend(traffic.get("findings", []))
            transactions = traffic.get("transactions", [])
            traffic_metrics = traffic.get("metrics", {})
        bundle = build_otlp_bundle(
            combined,
            transactions=transactions,
            traffic_metrics=traffic_metrics,
            run_id=wave_data.get("run_id"),
            time_unit_ns=wave_data.get("time_unit_ns") or 1,
            time_unit_label=wave_data.get("time_unit_label") or "tick")
        return combined, bundle

    def analyze():
        data = state["wave"]
        if data is None:
            findings_detail.setPlainText("Load a real VCD through the Waveforms tab first.")
            return
        try:
            report = diagnose(data, dut_roots=chosen_roots(dut),
                              tb_roots=chosen_roots(tb),
                              handshake_window=window.value())
        except (ValueError, TypeError) as exc:
            findings_detail.setPlainText("Diagnostic configuration error: " + str(exc))
            return
        state["report"] = report
        state["traffic"] = None
        page.axi4DecodeResult = None
        traffic_table.setRowCount(0)
        traffic_summary.setText("AXI4 decoder has not run")
        update_table(rtl_table, report["groups"]["rtl"])
        update_table(tb_table, report["groups"]["testbench"])
        rows = refresh_findings()
        findings_detail.setPlainText(
            json.dumps({"summary": report["summary"], "limits": report["limits"]},
                       indent=2))
        ai_text.clear()
        export_otel_button.setEnabled(True)
        send_dynatrace_button.setEnabled(True)
        axi_decode_button.setEnabled(True)
        page.summaryText = ("Observed %d signals, %d evidence candidates; "
                            "root cause NOT proven." %
                            (sum(len(v) for v in report["groups"].values()), len(rows)))

    def export_otel():
        report = state["report"]
        if report is None or state["wave"] is None:
            findings_detail.setPlainText("Analyze a loaded waveform before exporting telemetry.")
            return
        filename, _selected = QtWidgets.QFileDialog.getSaveFileName(
            page, "Export OpenTelemetry bundle",
            "wengold-otel-bundle.json", "JSON bundle (*.json)")
        if not filename:
            return
        try:
            combined, bundle = telemetry_report_and_bundle()
            target = write_otlp_bundle(filename, bundle)
            findings_detail.setPlainText(
                "OpenTelemetry bundle exported.\n"
                f"File: {target}\n"
                f"Trace ID: {bundle['metadata']['trace_id']}\n"
                f"Findings: {len(combined.get('findings', []))}\n"
                f"AXI4 transactions: {len(state['traffic'].get('transactions', [])) if state['traffic'] else 0}\n"
                "The JSON contains separate OTLP traces, metrics and logs payloads. "
                "No data was sent to an external service.")
        except (OSError, TypeError, ValueError) as exc:
            findings_detail.setPlainText(f"OpenTelemetry export failed: {exc}")

    class OtelUploadWorker(QtCore.QObject):
        succeeded = QtCore.pyqtSignal(object)
        failed = QtCore.pyqtSignal(str)

        def __init__(self, arguments):
            super().__init__()
            self.arguments = arguments

        @QtCore.pyqtSlot()
        def run(self):
            try:
                self.succeeded.emit(send_dynatrace_otlp(*self.arguments))
            except Exception as exc:
                detail = f"{type(exc).__name__}: {exc}"
                sent = getattr(exc, "sent_signals", ())
                if sent:
                    detail += "\nEarlier signal requests accepted: " + ", ".join(sent)
                self.failed.emit(detail)

    def send_to_dynatrace():
        report = state["report"]
        wave_data = state["wave"]
        endpoint_value = dynatrace_endpoint.text().strip()
        token_value = dynatrace_token.text().strip()
        if report is None or wave_data is None:
            findings_detail.setPlainText(
                "Analyze a loaded VCD before sending telemetry.")
            return
        if not endpoint_value or not token_value:
            findings_detail.setPlainText(
                "Enter the Dynatrace OTLP base URL and a Dynatrace platform token. "
                "The token is kept in this session only and is not saved.")
            return
        if state["otel_busy"]:
            return
        try:
            combined, bundle = telemetry_report_and_bundle()
        except (TypeError, ValueError) as exc:
            findings_detail.setPlainText(f"Telemetry preparation failed: {exc}")
            return
        state["otel_busy"] = True
        send_dynatrace_button.setEnabled(False)
        export_otel_button.setEnabled(False)
        findings_detail.setPlainText(
            "Sending OTLP Protobuf traces, metrics and logs to Dynatrace…")
        thread = QtCore.QThread(page)
        worker = OtelUploadWorker((bundle, endpoint_value, token_value))
        worker.moveToThread(thread)
        state["otel_thread"], state["otel_worker"] = thread, worker

        def upload_done():
            state["otel_busy"] = False
            # Drop the worker's reference to the token and clear the masked UI
            # field once this explicit upload attempt finishes.
            worker.arguments = ()
            dynatrace_token.clear()
            state["otel_worker"] = None
            state["otel_thread"] = None
            send_dynatrace_button.setEnabled(state["report"] is not None)
            export_otel_button.setEnabled(state["report"] is not None)
            thread.quit()

        def upload_success(result):
            findings_detail.setPlainText(
                "Dynatrace OTLP export accepted by the HTTP endpoints.\n"
                f"Endpoint: {result['endpoint_host']}\n"
                f"Signals sent: {', '.join(result['signals_sent'])}\n"
                "This confirms HTTP ingestion responses, not that a dashboard "
                "or downstream processing rule is configured.")
            upload_done()

        def upload_failed(message):
            findings_detail.setPlainText(
                "Dynatrace OTLP export failed.\n" + message +
                "\nIf one or more earlier signals were sent, inspect the "
                "message before retrying to avoid duplicate telemetry.")
            upload_done()

        worker.succeeded.connect(upload_success)
        worker.failed.connect(upload_failed)
        thread.started.connect(worker.run)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.start()

    send_dynatrace_button.clicked.connect(send_to_dynatrace)

    def decode_axi4_action():
        data = state["wave"]
        state["traffic"] = None
        page.axi4DecodeResult = None
        traffic_table.setRowCount(0)
        traffic_summary.setText("AXI4 decode failed or has not run")
        refresh_findings()
        if data is None:
            findings_detail.setPlainText("Load a real waveform before decoding AXI4.")
            return
        try:
            result = decode_axi4(
                data,
                prefix=axi_prefix.text().strip() or None,
                clock=axi_clock.text().strip() or None,
                max_stall_cycles=axi_stall_threshold.value())
        except (TypeError, ValueError) as exc:
            findings_detail.setPlainText("AXI4 decode configuration error: " + str(exc))
            return
        state["traffic"] = result
        protocol_errors = result["metrics"].get("protocol_errors", 0)
        if protocol_errors:
            first_finding = result.get("findings", [{}])[0]
            update_schematic(
                f"AXI4 decoder reported {protocol_errors} protocol error(s): "
                f"{first_finding.get('rule', first_finding.get('message', 'inspect findings'))}",
                "error")
        elif diff_state.get("report") and diff_state["report"].get("first_divergence"):
            # Preserve the differential alert if the AXI decoder found no
            # protocol errors; a value mismatch is not automatically a violation.
            first_item = diff_state["report"]["first_divergence"]
            update_schematic(
                f"Waveform divergence at {first_item['aligned_time']} "
                f"{first_item['time_unit']}: {first_item['signal']}",
                "warning")
        else:
            update_schematic("AXI4 decode completed with no reported protocol errors.")
        rows = result["transactions"]
        traffic_table.setRowCount(len(rows))
        for i, tx in enumerate(rows):
            values = (
                tx.get("operation", "").upper(),
                tx.get("transaction_id", ""),
                tx.get("address") or "UNKNOWN",
                f"{tx.get('beats', 0)}/{tx.get('expected_beats', 0)}",
                tx.get("response", "—"),
                tx.get("status", ""),
                f"{tx.get('start_time')} → {tx.get('end_time')}",
            )
            for c, value in enumerate(values):
                traffic_table.setItem(i, c, QtWidgets.QTableWidgetItem(str(value)))
        metrics = result["metrics"]
        traffic_summary.setText(
            f"AXI4: {len(rows)} completed transaction(s) · "
            f"{metrics['protocol_errors']} protocol error(s) · "
            f"{metrics['stall_cycles_total']} total stall cycle(s) · "
            f"{metrics['rising_edges']} sampled rising edges")
        refresh_findings()
        findings_detail.setPlainText(json.dumps({
            "status": result["status"],
            "signal_map": result["signal_map"],
            "metrics": result["metrics"],
            "findings": result["findings"],
            "limits": result["limits"],
        }, indent=2))
        page.axi4DecodeResult = result

    def select_transaction():
        row = traffic_table.currentRow()
        traffic = state["traffic"]
        if traffic is None or row < 0 or row >= len(traffic["transactions"]):
            return
        tx = traffic["transactions"][row]
        logical = "AWVALID" if tx.get("operation") == "write" else "ARVALID"
        signal_name = traffic.get("signal_map", {}).get(logical)
        if signal_name and on_crossprobe:
            on_crossprobe(signal_name)
        start_index = tx.get("attributes", {}).get("start_sample_index")
        if on_select_time and isinstance(start_index, int):
            on_select_time(start_index)
        findings_detail.setPlainText(json.dumps(tx, indent=2))

    def show_finding():
        row = finding_table.currentRow()
        rows = state["display_findings"]
        if row < 0 or row >= len(rows):
            return
        finding = rows[row]
        findings_detail.setPlainText(json.dumps(finding, indent=2))
        if on_crossprobe and finding["signals"]:
            on_crossprobe(finding["signals"][0])
        if on_select_time:
            on_select_time(finding["sample_index"])

    def select_signal(table):
        row = table.currentRow()
        if row < 0 or not on_crossprobe:
            return
        item = table.item(row, 0)
        if item:
            on_crossprobe(item.text())

    rtl_table.itemSelectionChanged.connect(lambda: select_signal(rtl_table))
    tb_table.itemSelectionChanged.connect(lambda: select_signal(tb_table))
    finding_table.itemSelectionChanged.connect(show_finding)
    traffic_table.itemSelectionChanged.connect(select_transaction)
    run.clicked.connect(analyze)
    axi_decode_button.clicked.connect(decode_axi4_action)
    export_otel_button.clicked.connect(export_otel)

    class AiWorker(QtCore.QObject):
        succeeded = QtCore.pyqtSignal(object)
        failed = QtCore.pyqtSignal(str)

        def __init__(self, arguments):
            super().__init__()
            self.arguments = arguments

        @QtCore.pyqtSlot()
        def run(self):
            try:
                self.succeeded.emit(explain_with_local_ai(*self.arguments))
            except Exception as exc:
                self.failed.emit(f"{type(exc).__name__}: {exc}")

    def do_explain():
        if state["report"] is None:
            ai_text.setPlainText("Analyze an actual loaded VCD before asking Local AI.")
            return
        if state["busy"]:
            return
        state["busy"] = True
        explain.setEnabled(False)
        ai_text.setPlainText("Calling selected LOCAL model with bounded waveform evidence…")
        ai_report = dict(state["report"])
        ai_report["findings"] = list(state["display_findings"])
        args = (ai_report, backend.currentText(), endpoint.text().strip(),
                model.text().strip())
        thread = QtCore.QThread(page)
        worker = AiWorker(args)
        worker.moveToThread(thread)
        state["thread"], state["worker"] = thread, worker

        def success(reply):
            ai_text.setPlainText(
                "AI HYPOTHESES — NOT VERIFIED\n"
                f"Model: {reply['model']}\n"
                f"Evidence SHA256: {reply['report_sha256']}\n\n"
                + reply["answer"])
            done()
        def failed(message):
            ai_text.setPlainText("LOCAL AI FAILED — no analysis produced\n" + message)
            done()
        def done():
            state["busy"] = False
            explain.setEnabled(True)
            thread.quit()
        worker.succeeded.connect(success)
        worker.failed.connect(failed)
        thread.started.connect(worker.run)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.start()

    explain.clicked.connect(do_explain)
    page.loadWave = lambda data: (state.update(wave=data), analyze())
    page.analyzeWave = analyze
    page.rtlSignals = rtl_table
    page.tbSignals = tb_table
    page.findingTable = finding_table
    page.aiFindings = ai_text
    page.axiPrefix = axi_prefix
    page.axiClock = axi_clock
    page.axiDecodeButton = axi_decode_button
    page.axiTransactions = traffic_table
    page.axiTrafficSummary = traffic_summary
    page.schematicView = schematic_view
    page.schematicAlert = schematic_alert
    page.rootEvidence = findings_detail
    return page
