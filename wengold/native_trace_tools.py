"""Extra native desktop views for aligned traces and protocol transactions."""
from __future__ import annotations

from .native_trace_load import load_paths
from .native_waveplot import build_wave_canvas
from .studio_workspace import waveform
from .wave_compare import compare, plot_window
from .wave_inspect import time_label
from .wave_protocol import decode


def invalidate_comparison_cache(state):
    """Discard loaded traces and results when either selected source changes."""
    state["a"] = state["b"] = state["diff"] = None


def make_trace_tools(root, QtCore, QtGui, QtWidgets, alert, focus_sample):
    page = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(page)
    workspaces = QtWidgets.QTabWidget()
    layout.addWidget(workspaces)
    state = {"trace": None, "a": None, "b": None, "diff": None}

    def tab(title):
        pane = QtWidgets.QWidget()
        vbox = QtWidgets.QVBoxLayout(pane)
        workspaces.addTab(pane, title)
        return vbox

    def row(parent):
        box = QtWidgets.QHBoxLayout()
        parent.addLayout(box)
        return box

    def edit(desc, name, bar):
        field = QtWidgets.QLineEdit()
        field.setPlaceholderText(desc)
        field.setAccessibleName(desc)
        field.setObjectName(name)
        bar.addWidget(field, 1)
        return field

    def combo(name, bar):
        control = QtWidgets.QComboBox()
        control.setObjectName(name)
        control.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        control.setMinimumContentsLength(10)
        bar.addWidget(control, 1)
        return control

    def button(label, name, bar, handler):
        control = QtWidgets.QPushButton(label)
        control.setObjectName(name)
        control.clicked.connect(handler)
        bar.addWidget(control)
        return control

    def label(text, parent, name=""):
        control = QtWidgets.QLabel(text)
        control.setObjectName(name)
        control.setWordWrap(True)
        control.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        parent.addWidget(control)
        return control

    def table(name, headers, parent):
        control = QtWidgets.QTableWidget(0, len(headers))
        control.setObjectName(name)
        control.setHorizontalHeaderLabels(headers)
        control.horizontalHeader().setStretchLastSection(True)
        control.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        control.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        parent.addWidget(control)
        return control

    def fill(widget, values):
        widget.clearContents()
        widget.setRowCount(len(values))
        for i, fields in enumerate(values):
            for j, value in enumerate(fields):
                text = "—" if value is None else str(value)
                item = QtWidgets.QTableWidgetItem(text)
                item.setToolTip(text)
                widget.setItem(i, j, item)

    diff_view = tab("Trace comparison")
    files_bar = row(diff_view)
    files_bar.addWidget(QtWidgets.QLabel("Baseline"))
    pick_a = combo("traceBaseline", files_bar)
    files_bar.addWidget(QtWidgets.QLabel("Candidate"))
    pick_b = combo("traceCandidate", files_bar)
    load_button = button("Load and compare", "traceCompare", files_bar, lambda: load_compare())
    options = row(diff_view)
    anchor_a = edit("Baseline anchor tick (optional)", "traceAnchorA", options)
    anchor_b = edit("Candidate anchor tick (optional)", "traceAnchorB", options)
    query = edit("Filter signal paths", "traceCompareFilter", options)
    button("Apply alignment", "traceAlign", options, lambda: align())
    diff_summary = label("Choose two traces. Default alignment uses their first captured timestamps.",
                         diff_view, "traceCompareSummary")
    results = table("traceCompareTable", ["Signal path", "First divergence", "Comparison"], diff_view)
    results.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
    canvases = []
    plots = QtWidgets.QHBoxLayout()
    diff_view.addLayout(plots)
    for title in ("Baseline", "Candidate"):
        section = QtWidgets.QVBoxLayout()
        plots.addLayout(section, 1)
        label(title, section)
        canvas = build_wave_canvas(QtCore, QtGui, QtWidgets)
        canvas.set_zoom(.65)
        scroll = QtWidgets.QScrollArea()
        scroll.setObjectName("tracePlot" + title)
        scroll.setMinimumHeight(107)
        scroll.setMaximumHeight(148)
        scroll.setWidget(canvas)
        section.addWidget(scroll)
        canvases.append((canvas, scroll))
    s1, s2 = (scroll.horizontalScrollBar() for _, scroll in canvases)
    s1.valueChanged.connect(s2.setValue)
    s2.valueChanged.connect(s1.setValue)
    empty = {"signals": [], "times": [], "cycles": 0}

    def display_time(tick, unit):
        if unit != "fs":
            return f"{tick} ticks"
        for magnitude, name in ((10**15, "s"), (10**12, "ms"), (10**9, "µs"),
                                (10**6, "ns"), (10**3, "ps")):
            if tick and tick % magnitude == 0:
                return f"{tick // magnitude} {name}"
        return f"{tick} fs"

    def show_diff():
        comparison = state["diff"]
        selected = results.currentRow()
        if not comparison or not 0 <= selected < len(comparison["rows"]):
            for canvas, _ in canvases:
                canvas.set_data(empty)
            return
        record = comparison["rows"][selected]
        center = record["first"] if record["first"] is not None else 0
        for side, (canvas, _) in zip(("a", "b"), canvases):
            data, cursor = plot_window(state[side], comparison, side, record["name"], center)
            canvas.set_data(data)
            if record["first"] is not None:
                canvas.cursors = cursor, None
                canvas.update()
        if record["first"] is not None:
            for canvas, scroll in canvases:
                scroll.ensureVisible(canvas.sample_x(cursor), 0, 55, 0)

    def align():
        if state["a"] is None or state["b"] is None:
            return
        try:
            anchors = (int(x.text()) if x.text().strip() else None for x in (anchor_a, anchor_b))
            result = compare(state["a"], state["b"], *anchors, query.text().strip())
        except ValueError as exc:
            clear_diff(str(exc))
            return
        state["diff"] = result
        rows = sorted(result["rows"], key=lambda r: (r["first"] is None,
                                                     r["first"] or 0, r["name"]))
        result["rows"] = rows
        with QtCore.QSignalBlocker(results):
            fill(results, [(r["name"], display_time(result["times"][r["first"]], result["unit"])
                            if r["first"] is not None else None, r["status"]) for r in rows])
        first = next((r for r in rows if r["first"] is not None), None)
        summary = [f"Overlap {display_time(result['times'][0], result['unit'])} to "
                   f"{display_time(result['times'][-1], result['unit'])}", f"{len(rows)} displayed paths"]
        if first:
            summary.append(f"First divergence: {first['name']} at "
                           f"{display_time(result['times'][first['first']], result['unit'])}")
        if result["unit"] != "fs":
            summary.append("timescales absent; raw ticks only")
        if any(t["samples_truncated"] or t["signals_omitted"] or t["unsupported_signals"]
               for t in (state["a"], state["b"])):
            summary.append("input capped or signals omitted")
        diff_summary.setText(" · ".join(summary))
        if rows:
            results.setCurrentCell(0, 0)
        show_diff()

    def invalidate_compare(_=None):
        # A selector change invalidates the loaded captures even if a previous
        # alignment attempt failed and already cleared the visible diff.
        invalidate_comparison_cache(state)
        clear_diff("File selection changed. Load the two traces to recompute the comparison.")

    def clear_diff(message):
        state["diff"] = None
        fill(results, [])
        show_diff()
        diff_summary.setText(message)

    def load_compare():
        baseline, candidate = pick_a.currentText(), pick_b.currentText()
        if not baseline or not candidate:
            clear_diff("Select both trace files first.")
            return
        load_button.setEnabled(False)
        state["a"] = state["b"] = None
        clear_diff("Loading selected traces…")

        def loaded(values, error):
            load_button.setEnabled(True)
            if (baseline, candidate) != (pick_a.currentText(), pick_b.currentText()):
                clear_diff("File selection changed. Load the two traces to recompute the comparison.")
            elif error:
                clear_diff(error)
            else:
                state["a"], state["b"] = values
                align()

        load_paths(page, QtCore, [baseline, candidate], lambda path: waveform(root, path), loaded)

    results.itemSelectionChanged.connect(show_diff)
    pick_a.currentTextChanged.connect(invalidate_compare)
    pick_b.currentTextChanged.connect(invalidate_compare)
    for field in (anchor_a, anchor_b, query):
        field.returnPressed.connect(align)

    protocol_view = tab("Protocol lanes")
    mapping = row(protocol_view)
    profile = combo("traceProtocolKind", mapping)
    profile.addItems(("APB", "AXI4", "AXI4-Lite"))
    prefix = edit("Signal prefix, e.g. tb.dut.", "traceProtocolPrefix", mapping)
    clock = edit("Clock path (optional)", "traceProtocolClock", mapping)
    reset = edit("Active-low reset (optional)", "traceProtocolReset", mapping)
    button("Decode loaded trace", "traceDecode", mapping, lambda: decode_trace())
    decode_summary = label(
        "Load a VCD or FST in Waveforms. Decode only the selected interface; changing controls at "
        "a sampling edge are ambiguous.", protocol_view, "traceProtocolSummary")
    lane_row = row(protocol_view)
    lane_filter = combo("traceLaneFilter", lane_row)
    lane_filter.addItem("All lanes")
    lane_row.addStretch(2)

    class LaneMap(QtWidgets.QWidget):
        def __init__(self):
            super().__init__()
            self.report = None
            self.markers = []
            self.setMinimumHeight(140)
            self.setObjectName("traceLaneTimeline")
            self.setAccessibleName("Protocol lanes. Use the transfer table for keyboard navigation.")

        def paintEvent(self, event):
            p = QtGui.QPainter(self)
            p.fillRect(self.rect(), QtGui.QColor("#edf2fa"))
            self.markers = []
            if not self.report:
                return
            times = self.report["times"]
            if not times:
                return
            total = max(1, times[-1] - times[0])
            p.setPen(QtGui.QColor("#354963"))
            p.drawText(8, 17, f"Transfers on rising edges · {time_label(times[0], self.report['timescale'])}"
                              f" to {time_label(times[-1], self.report['timescale'])}")
            for index, lane in enumerate(self.report["lanes"]):
                y = 36 + index * 20
                p.setPen(QtGui.QColor("#354963"))
                p.drawText(8, y + 4, lane)
                p.setPen(QtGui.QColor("#b5c5de"))
                p.drawLine(40, y, self.width() - 12, y)
                for item in self.report["events"]:
                    if item["lane"] != lane:
                        continue
                    x = 40 + round((self.width() - 52) * (item["tick"] - times[0]) / total)
                    p.setPen(QtGui.QColor("#a94a15" if item["ambiguous"] else "#2855ae"))
                    p.setBrush(p.pen().color())
                    p.drawEllipse(QtCore.QPoint(x, y), 4, 4)
                    self.markers.append((x, y, item["sample"]))

        def mousePressEvent(self, event):
            if event.button() == QtCore.Qt.MouseButton.LeftButton and self.markers:
                x, y = event.position().x(), event.position().y()
                px, py, sample = min(self.markers, key=lambda mark: abs(x - mark[0]) + abs(y - mark[1]))
                if abs(x - px) <= 8 and abs(y - py) <= 8:
                    focus_sample(sample)

    chart = LaneMap()
    protocol_view.addWidget(chart)
    events = table("traceLaneEvents", ["Lane", "Time", "Wait edges", "Observed fields"], protocol_view)
    transfers = table("traceProtocolTransactions",
                      ["Transaction", "ID", "Address", "End time", "Latency"], protocol_view)
    transfers.setMaximumHeight(145)
    proto = {"report": None, "shown": []}

    def show_events():
        report = proto["report"]
        if not report:
            fill(events, [])
            return
        chosen = lane_filter.currentText()
        proto["shown"] = [evt for evt in report["events"]
                          if chosen == "All lanes" or chosen == evt["lane"]]
        scale = report["timescale"]
        fill(events, [(evt["lane"], time_label(evt["tick"], scale), evt["wait"],
                       " · ".join([*(f"{k}={v}" for k, v in evt["fields"].items()),
                                  *(f"{k} ambiguous" for k in evt["ambiguous"])]))
                      for evt in proto["shown"]])

    def clear_protocol(message):
        proto.update(report=None, shown=[])
        chart.report = None
        chart.markers = []
        chart.update()
        fill(events, [])
        fill(transfers, [])
        lane_filter.clear()
        lane_filter.addItem("All lanes")
        decode_summary.setText(message)

    def decode_trace():
        if not state["trace"]:
            clear_protocol("Load a trace in Waveforms first.")
            return
        try:
            report = decode(state["trace"], profile.currentText(), prefix.text(), clock.text(), reset.text())
        except ValueError as exc:
            clear_protocol(str(exc))
            return
        proto["report"] = report
        chart.report = report
        chart.update()
        with QtCore.QSignalBlocker(lane_filter):
            lane_filter.clear()
            lane_filter.addItems(["All lanes", *report["lanes"]])
        show_events()
        scale = report["timescale"]
        fill(transfers, [(item["kind"], item["id"], item["addr"], time_label(item["end"], scale),
                          time_label(item["end"] - item["start"], scale) if item["start"] is not None else None)
                         for item in report["transactions"]])
        summary = [f"{len(report['events'])} observed transfers",
                   f"{report['skipped_control']} ambiguous channel edges skipped",
                   f"{report['reset_edges']} reset/unknown-reset edges excluded"]
        if profile.currentText().startswith("AXI"):
            summary += [f"{report['unpaired_responses']} unpaired responses",
                        f"{report['pending_addresses']} tracked outstanding addresses"]
            if report["pairing_uncertain"]:
                summary.append("Pairing uncertain until reset: " + ", ".join(report["pairing_uncertain"]))
        if report["missing_lanes"]:
            summary.append("Not captured: " + ", ".join(report["missing_lanes"]))
        if not report["reset"]:
            summary.append("reset not captured")
        if any(state["trace"].get(flag) for flag in ("samples_truncated", "signals_omitted",
                                                     "unsupported_signals")):
            summary.append("input capped or signals omitted")
        decode_summary.setText(" · ".join(summary))

    def protocol_mapping_changed(_=None):
        if proto["report"]:
            clear_protocol("Interface mapping changed. Decode the loaded trace again.")

    profile.currentTextChanged.connect(protocol_mapping_changed)
    for field in (prefix, clock, reset):
        field.textChanged.connect(protocol_mapping_changed)
    lane_filter.currentTextChanged.connect(show_events)
    events.cellDoubleClicked.connect(lambda i, _: focus_sample(proto["shown"][i]["sample"]))
    transfers.cellDoubleClicked.connect(
        lambda i, _: focus_sample(proto["report"]["transactions"][i]["sample"]))

    def set_files(paths):
        for index, widget in enumerate((pick_a, pick_b)):
            previous = widget.currentText()
            with QtCore.QSignalBlocker(widget):
                widget.clear()
                widget.addItems(paths)
                if previous in paths:
                    widget.setCurrentText(previous)
                elif len(paths) > index:
                    widget.setCurrentIndex(index)
            if previous and widget.currentText() != previous:
                invalidate_compare()

    def set_trace(trace):
        state["trace"] = trace
        clear_protocol(f"Loaded {trace['source']}. Select the interface and decode.")

    page.setFiles = set_files
    page.setTrace = set_trace
    return page
