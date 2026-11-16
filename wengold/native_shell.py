"""Shared shell styling and workspace navigation for native Qt Studio."""

MUTED = "#516079"

STYLESHEET = """
QMainWindow, QWidget { background: #f2f5fa; color: #1b2840; }
QLabel, QCheckBox { background: transparent; }
QMenuBar, QMenu, QStatusBar { background: #ffffff; color: #33425c; }
QMenuBar { border-bottom: 1px solid #dce4ef; }
QMenuBar::item:selected, QMenu::item:selected { background: #e7efff; }
QFrame#strip, QFrame#workspaceHeading {
    background: #ffffff; border-bottom: 1px solid #dce4ef; }
QFrame#workspaceRail { background: #162238; border-right: 1px solid #0e1a2e; }
QLabel#railBrand { font-size: 17px; font-weight: 800; color: #f6f8ff; }
QLabel#railSubtitle { color: #b5c4de; }
QListWidget#workspaceNavigation {
    background: #162238; color: #d9e4f9; border: 0; outline: 0; }
QListWidget#workspaceNavigation::item { padding: 5px 7px; border-radius: 5px; }
QListWidget#workspaceNavigation::item:selected {
    background: #36568b; color: #ffffff; }
QListWidget#workspaceNavigation::item:hover:!selected { background: #243857; }
QListWidget#workspaceNavigation::item:focus { border: 1px solid #87a7ed; }
QListWidget#workspaceNavigation::item:disabled { background: transparent; }
QLabel#project { font-size: 18px; font-weight: 750; }
QLabel#revision, QLabel#workspaceSubtitle, QLabel#metricHint { color: #516079; }
QLabel#workspaceTitle { font-size: 20px; font-weight: 750; }
QLabel#sectionTitle { color: #40516d; font-size: 11px; font-weight: 700; }
QFrame[card="true"] {
    background: #ffffff; border: 1px solid #dce4ef; border-radius: 8px; }
QLabel#metricNumber { color: #233e70; font-size: 24px; font-weight: 750; }
QLabel#graphQuality { padding: 5px 8px; border-radius: 5px;
    background: #e7eefb; color: #264577; font-weight: 650; }
QLabel#graphQuality[attention="true"] { background: #fff0cc; color: #744e00; }
QLabel#studioStatus { padding: 5px 12px; color: #43536d; }
QLabel#studioStatus[severity="error"] { background: #fff0ef; color: #9c2929; }
QTabWidget::pane { border: 1px solid #dce4ef; background: #ffffff; }
QTabWidget#studioTabs::pane { border: 0; }
QTabBar::tab {
    background: #e9eef7; color: #40516d; padding: 7px 10px;
    border: 1px solid #dce4ef; border-bottom: 0; }
QTabBar::tab:selected { background: #ffffff; color: #224b9e; font-weight: 700; }
QTabBar::tab:hover { background: #e0eafe; }
QTreeWidget, QTableWidget, QTextEdit, QPlainTextEdit, QLineEdit, QComboBox, QSpinBox {
    background: #ffffff; color: #1b2840; border: 1px solid #d5dfed;
    border-radius: 4px; selection-background-color: #dce9ff; selection-color: #132d57; }
QTreeWidget, QTableWidget { alternate-background-color: #f5f8fd; }
QHeaderView::section {
    background: #edf2fa; color: #354963; border: 0; padding: 5px 7px;
    border-bottom: 1px solid #dce4ef; font-weight: 650; }
QPushButton {
    background: #ffffff; color: #263954; border: 1px solid #c8d5e7;
    border-radius: 5px; padding: 5px 9px; font-weight: 600; }
QPushButton:hover { background: #e9f1ff; border-color: #8daee9; }
QPushButton[primary="true"] { background: #2855ae; color: #ffffff; border-color: #2855ae; }
QPushButton[primary="true"]:hover { background: #23468f; }
QPushButton:disabled { background: #edf1f7; color: #64748b; border-color: #dce4ef; }
QPushButton:focus, QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus {
    border: 1px solid #2855ae; }
QLineEdit, QComboBox, QSpinBox { padding: 4px 6px; }
QToolTip { background: #ffffff; color: #1b2840; border: 1px solid #9aacc9; padding: 5px; }
QSplitter::handle { background: #e2e9f4; }
QDockWidget::title { background: #e7eef9; color: #263954; padding: 6px 9px; }
QTextEdit#ciwTranscript { font-family: monospace; }
QLineEdit#ciwCommandInput, QLabel#ciwPromptLabel { font-family: monospace; }
QLabel#ciwPromptLabel { color: #254d99; font-weight: 750; }
"""

SECTIONS = (
    ("PROJECT", ("Overview", "RTL Editor")),
    ("VERIFY", ("DV Workflow", "Formal", "Jobs & Signoff")),
    ("DEBUG", ("Waveforms", "Wave Debug", "Trace Tools")),
    ("TOOLS", ("Synthesis / PPA", "Agents", "Workers", "Local AI")),
)

DESCRIPTIONS = {
    "Overview": "Browse project sources and inspect the indexed design graph.",
    "RTL Editor": "Open, edit and check project source files.",
    "DV Workflow": "Connect specifications, tests, regression logs and coverage evidence.",
    "Formal": "Run a bounded property check or inspect an imported formal report.",
    "Jobs & Signoff": "Inspect local tool outcomes, evidence freshness and review decisions.",
    "Waveforms": "Open VCD or FST and inspect sampled signals and source matches.",
    "Trace Tools": "Compare aligned traces and inspect APB and AXI transaction lanes.",
    "Wave Debug": "Compare design and testbench activity and investigate suspicious signals.",
    "Synthesis / PPA": "Run configured synthesis and inspect netlists and estimates.",
    "Agents": "Inspect the graph-based verification plan.",
    "Workers": "Inspect or submit jobs in the persistent worker queue.",
    "Local AI": "Connect a local model and review generated drafts.",
}


def make_navigation(QtCore, QtWidgets):
    rail = QtWidgets.QFrame()
    rail.setObjectName("workspaceRail")
    rail.setFixedWidth(172)
    layout = QtWidgets.QVBoxLayout(rail)
    layout.setContentsMargins(10, 14, 10, 8)
    layout.setSpacing(5)
    brand = QtWidgets.QLabel("WENGOLD")
    brand.setObjectName("railBrand")
    layout.addWidget(brand)
    subtitle = QtWidgets.QLabel("Silicon Studio")
    subtitle.setObjectName("railSubtitle")
    layout.addWidget(subtitle)
    layout.addSpacing(4)
    navigation = QtWidgets.QListWidget()
    navigation.setObjectName("workspaceNavigation")
    navigation.setAccessibleName("Engineering workspaces")
    navigation.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    navigation.setTextElideMode(QtCore.Qt.TextElideMode.ElideRight)
    layout.addWidget(navigation, 1)
    return rail, navigation


def sync_navigation(navigation, titles, QtCore, QtGui, QtWidgets):
    """Populate the rail from actual pages so missing and new tabs stay honest."""
    rows = {}
    navigation.clear()
    for section, names in (*SECTIONS, ("OTHER", tuple(t for t in titles if t not in DESCRIPTIONS))):
        available = [name for name in names if name in titles]
        if not available:
            continue
        group = QtWidgets.QListWidgetItem(section, navigation)
        group.setFlags(QtCore.Qt.ItemFlag.NoItemFlags)
        group.setForeground(QtGui.QColor("#a8badc"))
        font = group.font()
        font.setBold(True)
        font.setPointSize(8)
        group.setFont(font)
        for title in available:
            item = QtWidgets.QListWidgetItem(title, navigation)
            item.setData(QtCore.Qt.ItemDataRole.UserRole, title)
            item.setToolTip(DESCRIPTIONS.get(title, title))
            rows[title] = item
    return rows
