"""Native trace inspection UI. Only observed VCD data enters WaveDrom exports."""
from __future__ import annotations

from fnmatch import fnmatchcase
import json
from pathlib import Path

from .native_waveplot import build_wave_canvas
from .studio_workspace import waveform
from .wave_inspect import nearest_sample, next_change, render_value, time_at, time_label, wave_drom


def make_wave_view(root, QtCore, QtGui, QtWidgets, alert, crossprobe, open_source):
    page = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(page)
    layout.setContentsMargins(12, 10, 12, 8)
    layout.setSpacing(6)
    role = QtCore.Qt.ItemDataRole.UserRole

    def row():
        result = QtWidgets.QHBoxLayout()
        layout.addLayout(result)
        return result

    def button(text, name, bar):
        control = QtWidgets.QPushButton(text)
        control.setObjectName(name)
        bar.addWidget(control)
        return control

    file_bar = row()
    picker = QtWidgets.QComboBox()
    picker.setObjectName("waveFilePicker")
    picker.setAccessibleName("Project VCD files")
    picker.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    picker.setMinimumContentsLength(12)
    file_bar.addWidget(picker, 1)
    load = button("Load VCD", "waveLoad", file_bar)
    refresh = button("Refresh files", "waveRefresh", file_bar)
    export = button("Export WaveDrom…", "waveExportDrom", file_bar)
    export.setToolTip("Export the pinned signals and the A/B time window as observed WaveJSON")

    details = QtWidgets.QLabel("Load a project VCD to inspect real sampled signal values.")
    details.setObjectName("waveTraceDetails")
    details.setTextFormat(QtCore.Qt.TextFormat.PlainText)
    details.setWordWrap(True)
    layout.addWidget(details)

    controls = row()
    filter_ = QtWidgets.QLineEdit()
    filter_.setObjectName("waveSignalFilter")
    filter_.setAccessibleName("Filter signals by hierarchy or name")
    filter_.setPlaceholderText("Filter signal paths, e.g. tb.dut.*")
    filter_.setClearButtonEnabled(True)
    controls.addWidget(filter_, 1)
    pinned_only = QtWidgets.QCheckBox("Pinned only")
    pinned_only.setObjectName("wavePinnedOnly")
    controls.addWidget(pinned_only)
    radix = QtWidgets.QComboBox()
    radix.setObjectName("waveRadix")
    radix.setAccessibleName("Bus value radix")
    radix.addItems(["Hex", "Binary", "Unsigned", "Signed"])
    controls.addWidget(radix)
    zoom_out = button("Zoom −", "waveZoomOut", controls)
    zoom_in = button("Zoom +", "waveZoomIn", controls)

    cursor_bar = row()
    cursor_choice = QtWidgets.QComboBox()
    cursor_choice.setObjectName("waveActiveCursor")
    cursor_choice.setAccessibleName("Active measurement cursor")
    cursor_choice.addItems(["Cursor A", "Cursor B"])
    cursor_bar.addWidget(cursor_choice)
    jump = QtWidgets.QLineEdit()
    jump.setObjectName("waveJumpTick")
    jump.setPlaceholderText("Go to VCD tick")
    jump.setAccessibleName("Go to nearest VCD tick")
    jump.setMaximumWidth(168)
    cursor_bar.addWidget(jump, 1)
    go = button("Go", "waveGoToTick", cursor_bar)
    previous = button("Previous change", "wavePreviousEdge", cursor_bar)
    following = button("Next change", "waveNextEdge", cursor_bar)
    cursor_bar.addStretch(1)
    bookmark_bar = row()
    add_bookmark = button("Bookmark cursor…", "waveAddBookmark", bookmark_bar)
    bookmarks = QtWidgets.QComboBox()
    bookmarks.setObjectName("waveBookmarks")
    bookmarks.setAccessibleName("Bookmarks for the loaded trace")
    bookmarks.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    bookmarks.setMinimumContentsLength(15)
    bookmark_bar.addWidget(bookmarks, 1)
    use_bookmark = button("Jump to bookmark", "waveUseBookmark", bookmark_bar)
    drop_bookmark = button("Remove", "waveDropBookmark", bookmark_bar)
    for control in (add_bookmark, use_bookmark, drop_bookmark):
        control.setEnabled(False)
    cursors_label = QtWidgets.QLabel(
        "Click a sample for A, Shift-click or right-click for B. Check Pin to include a signal in export.")
    cursors_label.setWordWrap(True)
    cursors_label.setObjectName("waveCursorReadout")
    layout.addWidget(cursors_label)

    splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
    canvas = build_wave_canvas(QtCore, QtGui, QtWidgets)
    scroll = QtWidgets.QScrollArea()
    scroll.setObjectName("waveformTimeline")
    scroll.setWidget(canvas)
    splitter.addWidget(scroll)
    table = QtWidgets.QTableWidget(0, 5)
    table.setObjectName("waveformTable")
    table.setAccessibleName("Signal pins and values at cursors A and B")
    table.setHorizontalHeaderLabels(["Signal path", "Bits", "Value at A", "Value at B", "Pin"])
    header = table.horizontalHeader()
    header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
    for col in range(1, 5):
        header.setSectionResizeMode(col, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
    table.verticalHeader().hide()
    table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
    table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setAlternatingRowColors(True)
    splitter.addWidget(table)
    splitter.setSizes([250, 160])
    splitter.setStretchFactor(0, 3)
    splitter.setStretchFactor(1, 2)
    layout.addWidget(splitter, 1)
    jump_source = QtWidgets.QHBoxLayout()
    match_picker = QtWidgets.QComboBox()
    match_picker.setObjectName("waveSourceMatch")
    match_picker.setAccessibleName("Lexical source matches for the selected signal")
    match_picker.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    match_picker.setMinimumContentsLength(16)
    jump_source.addWidget(match_picker, 1)
    open_match = button("Open selected source match", "waveOpenSourceMatch", jump_source)
    open_match.setEnabled(False)
    layout.addLayout(jump_source)
    probe = QtWidgets.QPlainTextEdit()
    probe.setObjectName("rtlCrossProbe")
    probe.setReadOnly(True)
    probe.setPlaceholderText("Select a signal to look for RTL source matches.")
    probe.setMaximumHeight(80)
    layout.addWidget(probe)

    state = {"data": None, "signals": {}, "pinned": set(), "cursor": [None, None],
             "selecting": False}

    def active_cursor():
        return cursor_choice.currentIndex()

    def time_text(value):
        return time_label(value, state["data"].get("timescale"))

    def update_values():
        data = state["data"]
        if not data:
            return
        a, b = state["cursor"]
        canvas.cursors = a, b
        canvas.radix = radix.currentText()
        canvas.update()
        message = []
        for label, index in zip("AB", (a, b)):
            message.append(f"{label} {time_text(time_at(data, index))}" if index is not None else f"{label} not set")
        if a is not None and b is not None:
            message.append(f"Δ {time_text(abs(time_at(data, b) - time_at(data, a)))}")
        message.append(f"{len(state['pinned'])} pinned")
        add_bookmark.setEnabled(state["cursor"][active_cursor()] is not None)
        cursors_label.setText("  ·  ".join(message))
        export.setEnabled(bool(state["pinned"]) and a is not None and b is not None and a != b)
        for index in range(table.rowCount()):
            signal = state["signals"][table.item(index, 0).data(role)]
            for col, cursor in ((2, a), (3, b)):
                label = render_value(signal, cursor, radix.currentText()) if cursor is not None else "—"
                item = table.item(index, col)
                item.setText(label if len(label) <= 35 else label[:32] + "…")
                item.setToolTip(label)

    def selected_name():
        item = table.item(table.currentRow(), 0)
        return item.data(role) if item is not None else None

    def inspect_source(name):
        message, matches = crossprobe(name)
        probe.setPlainText(message)
        match_picker.clear()
        for match in matches:
            match_picker.addItem(f"{match['file']}:{match['line']}", match)
        open_match.setEnabled(bool(matches))

    def select_signal(name):
        state["selecting"] = True
        try:
            for i in range(table.rowCount()):
                if table.item(i, 0).data(role) == name:
                    table.setCurrentCell(i, 0)
                    break
            inspect_source(name)
        finally:
            state["selecting"] = False

    def refresh_rows():
        selected = selected_name()
        query = filter_.text().strip().casefold()
        glob = any(ch in query for ch in "*?")
        shown = []
        with QtCore.QSignalBlocker(table):
            table.setRowCount(0)
            for name, signal in state["signals"].items():
                if pinned_only.isChecked() and name not in state["pinned"]:
                    continue
                if query and not (fnmatchcase(name.casefold(), query) if glob else query in name.casefold()):
                    continue
                i = table.rowCount()
                table.insertRow(i)
                shown.append(signal)
                for col, value in enumerate((name, str(signal["width"]), "—", "—", "")):
                    item = QtWidgets.QTableWidgetItem(value)
                    item.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled | QtCore.Qt.ItemFlag.ItemIsSelectable)
                    if col == 0:
                        item.setData(role, name)
                    if col == 4:
                        item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
                        item.setCheckState(QtCore.Qt.CheckState.Checked if name in state["pinned"]
                                           else QtCore.Qt.CheckState.Unchecked)
                    table.setItem(i, col, item)
                if name == selected:
                    table.setCurrentCell(i, 0)
            update_values()
        canvas.set_signals(shown)
        if selected_name() is None:
            match_picker.clear()
            open_match.setEnabled(False)
            probe.clear()

    def update_readouts():
        with QtCore.QSignalBlocker(table):
            update_values()

    def mark(index, which=None, reveal=False):
        data = state["data"]
        if not data or not isinstance(index, int) or not 0 <= index < data["cycles"]:
            return
        chosen = active_cursor() if which is None else which
        state["cursor"][chosen] = index
        update_readouts()
        if reveal:
            scroll.ensureVisible(canvas.sample_x(index), 0, 95, 0)

    def jump_to_tick():
        if not state["data"] or not state["data"]["times"]:
            return
        try:
            tick = int(jump.text().strip())
        except ValueError:
            alert("Enter a VCD tick as an integer", True)
            return
        mark(nearest_sample(state["data"]["times"], tick), reveal=True)

    def move_change(direction):
        name = selected_name()
        cursor = state["cursor"][active_cursor()]
        if name is None:
            alert("Select a signal before jumping to a value change", True)
            return
        i = next_change(state["signals"][name], 0 if cursor is None else cursor, direction)
        if i is None:
            alert("No more value changes in that direction")
        else:
            mark(i, reveal=True)

    def save_bookmark():
        index = state["cursor"][active_cursor()]
        if index is None:
            return
        caption, confirmed = QtWidgets.QInputDialog.getText(
            page, "Bookmark waveform sample", "Label (e.g. REQ-DATA failure)")
        if not confirmed or not caption.strip():
            return
        title = caption.strip()[:100] + " · " + time_text(state["data"]["times"][index])
        bookmarks.addItem(title, index)
        bookmarks.setCurrentIndex(bookmarks.count() - 1)

    def toggle_bookmark_actions(index):
        for control in (use_bookmark, drop_bookmark):
            control.setEnabled(index >= 0)

    def go_bookmark():
        index = bookmarks.currentData()
        if index is not None:
            mark(index, reveal=True)

    def pin_changed(item):
        if item.column() != 4:
            return
        name = table.item(item.row(), 0).data(role)
        if item.checkState() == QtCore.Qt.CheckState.Checked:
            state["pinned"].add(name)
        else:
            state["pinned"].discard(name)
        if pinned_only.isChecked():
            refresh_rows()
        else:
            update_readouts()

    def selection_changed():
        name = selected_name()
        if name and not state["selecting"]:
            inspect_source(name)
        elif not state["selecting"]:
            match_picker.clear()
            open_match.setEnabled(False)
            probe.clear()

    def change_zoom(ratio):
        index = state["cursor"][active_cursor()]
        canvas.set_zoom(canvas.zoom * ratio)
        if index is not None:
            scroll.ensureVisible(canvas.sample_x(index), 0, 95, 0)

    def load_trace():
        if not picker.currentText():
            alert("No supported VCD files found in project evidence directories", True)
            return
        try:
            data = waveform(root, picker.currentText())
        except Exception as exc:
            alert(f"Waveform load failed: {exc}", True)
            return
        state.update(data=data, signals={s["name"]: s for s in data["signals"]},
                     pinned=set(), cursor=[0 if data["cycles"] else None, None])
        with QtCore.QSignalBlocker(pinned_only):
            pinned_only.setChecked(False)
        with QtCore.QSignalBlocker(filter_):
            filter_.clear()
        with QtCore.QSignalBlocker(table):
            table.setRowCount(0)
        cursor_choice.setCurrentIndex(0)
        bookmarks.clear()
        jump.clear()
        probe.clear()
        match_picker.clear()
        open_match.setEnabled(False)
        canvas.set_data(data)
        scroll.horizontalScrollBar().setValue(0)
        refresh_rows()
        summary = [f"{len(data['signals'])} digital signals", f"{data['cycles']} observed timestamps",
                   f"VCD scale {data['timescale'] or 'unknown'}", "sample-spaced view"]
        if data["samples_truncated"]:
            summary.append("trace truncated by viewer limits")
        if data["signals_omitted"] or data["unsupported_signals"]:
            summary.append(f"{data['signals_omitted'] + data['unsupported_signals']} signals omitted")
        details.setText("  ·  ".join(summary))
        page.traceLoaded(data)
        alert(f"Opened observed VCD {data['source']}")

    def export_window():
        a, b = state["cursor"]
        signals = [v for k, v in state["signals"].items() if k in state["pinned"]]
        try:
            encoded = wave_drom(state["data"], signals, a, b, radix.currentText())
        except ValueError as exc:
            alert(str(exc), True)
            return
        name, _ = QtWidgets.QFileDialog.getSaveFileName(
            page, "Export observed timing as WaveDrom", "observed-waveform.json",
            "WaveJSON (*.json)")
        if not name:
            return
        try:
            target = Path(name)
            if target.suffix.lower() != ".json":
                raise ValueError("Choose a .json output name")
            save = QtCore.QSaveFile(str(target))
            payload = (json.dumps(encoded, indent=2, ensure_ascii=True) + "\n").encode("utf-8")
            if not save.open(QtCore.QIODevice.OpenModeFlag.WriteOnly):
                raise OSError(save.errorString())
            if save.write(payload) != len(payload) or not save.commit():
                raise OSError(save.errorString())
        except (OSError, ValueError) as exc:
            alert(f"WaveDrom export failed: {exc}", True)
            return
        alert(f"Exported observed VCD window to {target.name}")

    def set_files(paths):
        previous_path = picker.currentText()
        picker.clear()
        picker.addItems(paths)
        if previous_path in paths:
            picker.setCurrentText(previous_path)

    def open_current_match():
        match = match_picker.currentData()
        if match:
            open_source(match["file"], match["line"])

    open_match.clicked.connect(open_current_match)
    load.clicked.connect(load_trace)
    refresh.clicked.connect(lambda: page.refreshFiles())
    filter_.textChanged.connect(refresh_rows)
    pinned_only.toggled.connect(refresh_rows)
    radix.currentTextChanged.connect(update_readouts)
    cursor_choice.currentIndexChanged.connect(update_readouts)
    add_bookmark.clicked.connect(save_bookmark)
    bookmarks.currentIndexChanged.connect(toggle_bookmark_actions)
    use_bookmark.clicked.connect(go_bookmark)
    drop_bookmark.clicked.connect(lambda: bookmarks.removeItem(bookmarks.currentIndex()))
    zoom_in.clicked.connect(lambda: change_zoom(1.5))
    zoom_out.clicked.connect(lambda: change_zoom(1 / 1.5))
    go.clicked.connect(jump_to_tick)
    jump.returnPressed.connect(jump_to_tick)
    previous.clicked.connect(lambda: move_change(-1))
    following.clicked.connect(lambda: move_change(1))
    table.itemChanged.connect(pin_changed)
    table.itemSelectionChanged.connect(selection_changed)
    canvas.signalSelected.connect(select_signal)
    canvas.cursorSelected.connect(lambda index, set_b: mark(index, int(set_b)))
    export.clicked.connect(export_window)
    export.setEnabled(False)
    page.traceLoaded = lambda _data: None
    page.refreshFiles = lambda: None
    page.setFiles = set_files
    page.selectSignal = select_signal
    def focus_sample(index):
        cursor_choice.setCurrentIndex(0)
        mark(index, 0, reveal=True)

    page.focusSample = focus_sample
    page.waveTable = table
    page.waveCanvas = canvas
    return page
