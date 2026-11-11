# Installing WENGOLD on Linux

## Recommended: complete native Linux installation

To install the real PyQt6 Silicon Studio, local source parser and GUI launcher
in an **isolated virtual environment** without changing the system Python:

```sh
git pull origin main
sh linux/install-desktop.sh
~/.local/bin/wengold desktop --native /absolute/path/to/rtl
```

On Rocky Linux 9, Python 3.11 or later must be installed alongside the default
system Python 3.9 (do not replace /usr/bin/python3):

```sh
sudo dnf install python3.11 python3.11-pip
sh linux/install-desktop.sh --python python3.11
```

On Ubuntu / Debian, install Python 3.11+ and its venv package if unavailable.
Native Qt also requires system EGL/GL libraries; for Ubuntu, if an import fails:

```sh
sudo apt install libegl1 libgl1 libopengl0 libxkbcommon-x11-0 libxcb-cursor0
```

The desktop installer places third-party dependencies under
`~/.local/share/wengold-venv`, copies WENGOLD to `~/.local/share/wengold`,
and writes `~/.local/bin/wengold` plus the desktop menu entry. Its launcher
runs the **same** Python interpreter that owns PyQt6, avoiding mismatches
between system Python and pip-installed packages. To install formal tools,
use `sh linux/install-desktop.sh --formal`. This installer requires network
access or packages available to pip; it fails clearly rather than claiming
a GUI is installed without Qt. Remove it with `sh linux/uninstall.sh`.

Use `sh linux/install.sh` only for the minimal CLI-only installation without
automatically installing optional GUI dependencies.

**Debian package:** The .deb launcher now executes WENGOLD CLI for subcommands
and the application menu explicitly requests the native desktop. The package
requires Python 3.11+ and recommends PyQt6. Linux distributions whose system
Python is older should use `install-desktop.sh` rather than the .deb.

---

Three ways, depending on what you want.

## 1. Per-user install (no root)

```sh
sh linux/install.sh
```

Everything goes under `~/.local`, which is already on the XDG search path, so the
app appears in your application menu without a logout:

```
~/.local/bin/wengold
~/.local/share/wengold/wengold/          the package
~/.local/share/applications/wengold.desktop
~/.local/share/icons/hicolor/scalable/apps/wengold.svg
```

`sh linux/install.sh --check` reports what is missing and changes nothing.
`sh linux/install.sh --prefix DIR` installs somewhere else.

> The script is invoked with `sh` rather than `./install.sh` because a clone does
> not always keep the executable bit, and an installer that fails with
> "Permission denied" on line 1 is a bad first impression.

## 2. System-wide (root)

```sh
sudo sh linux/install.sh --system
```

Same layout, under `/usr/local`.

## 3. Debian package

```sh
sh linux/build-deb.sh
sudo dpkg -i dist/wengold_*_all.deb
sudo apt remove wengold            # uninstalls like any other package
```

`Architecture: all` — the package is pure Python, nothing is compiled. PyQt6 is a
**Recommends**, not a Depends: without it `wengold desktop` still starts in a
browser window, and a hard dependency would make the package uninstallable on a
machine with no Qt.

## The native window needs PyQt6

```sh
python3 -m pip install --user PyQt6
```

Without it, `wengold` launches the app in a browser window instead and says so in
one line. It does not refuse to start: an app that fails over a packaging detail
is worse than a tab.

## Uninstalling the script install

```sh
sh linux/uninstall.sh              # or --system, or --prefix DIR
```

It removes exactly the four paths above. Your projects, and the `.tof/` index
directories inside them, are untouched.

## What each file is

| file | what it does |
| --- | --- |
| `install.sh` | per-user or system install, then verifies the package imports |
| `uninstall.sh` | removes what `install.sh` created, nothing else |
| `build-deb.sh` | builds `dist/wengold_<version>_all.deb` |
| `wengold.desktop.in` | the launcher template, `@BIN@` and `@ICON@` substituted |
| `wengold.svg` | the icon, installed into the hicolor theme |

## Verified

Each of these was run, not assumed:

- `install.sh` into a throwaway `HOME` — the launcher it wrote then started the
  native window from the installed copy, with no repository on `PYTHONPATH`.
- `uninstall.sh` removes all four paths.
- `build-deb.sh` produces a 200 KB package with `root/root` ownership and clean
  directory modes; extracting it with `dpkg-deb -x` and running the payload starts
  the app.

## Silicon Studio — unified native Linux window

Install Python 3.11+ and PyQt6, then install the launcher:

```sh
python3 -m pip install --user PyQt6 pyslang
sh linux/install.sh
wengold desktop /absolute/path/to/rtl-project
```

The desktop application now has native PyQt6 tabs for Overview, RTL Editor,
Waveforms, Formal, Jobs & Signoff, and Agents. All share the same local
verification state and project-local evidence ledger. The application launcher
can also be opened from your Linux application menu.

Screenshot test without a running desktop session:

```sh
QT_QPA_PLATFORM=offscreen python3 -m wengold.native /absolute/path/to/rtl-project --screenshot studio.png
```

The native RTL editor safely opens and updates existing source files, refusing
to overwrite an externally modified file. The waveform tab reads actual project
VCDs, searches RTL for exact identifier matches, and does not invent traces.
The formal tab queues bounded checks; the job tab shows evidence and reviewer
decisions. Acceptance is never equivalent to production tapeout signoff.

For a true Linux window, PyQt6 must be present. When it is missing, the CLI may
fall back to a browser interface rather than silently pretending to be native.

Run the Qt tests with:

```sh
QT_QPA_PLATFORM=offscreen python3 -m pytest -q tests/test_native_studio.py tests/test_native_app.py
```


## Linux Studio hardening and dedicated smoke validation

Native Waveforms now includes a zoomable Qt timeline. It renders actual VCD timestamps,
high/low/unknown scalar values, and bus sample values; click a waveform row for a
lexical RTL cross-probe. This is not a full timing-accurate mixed-signal debugger.

Studio job history is restored from the project-local hash-chained evidence
ledger after restart. Previously unfinished jobs appear as interrupted,
and are not silently rerun. New work uses a single serialized local worker,
not distributed scheduling.

Accept Proof requires an optional reviewer credential configured in the launch
environment. Calculate its SHA-256 digest securely, then set
WENGOLD_REVIEW_KEY_SHA256 before launching the Linux Qt app.
Reject Evidence remains available without a credential. This shared secret
is a local approval gate, not user identity verification or authenticated tapeout
signoff; the entered reviewer name is still self-asserted. Keep the password
private and never commit its digest to the repository.

Desktop launchers installed via linux/install.sh force native Qt mode,
rather than silently opening a browser. The native window requires PyQt6.

Dedicated workflow: .github/workflows/linux-desktop-smoke.yml
This workflow runs on Ubuntu with a real offscreen Qt render, all focused
native tests, source compilation, and launcher installation.


## Command Interpreter Window (CIW)

Silicon Studio's native Linux window includes a persistent, dockable Command
Interpreter Window below the engineering workspaces. It remains available
when switching RTL Editor, Waveforms, Formal, Agents, and Workers.

- Supported WENGOLD commands run through the existing guarded interpreter.
- Up/Down navigate in-session command history; Escape clears the input.
- Type `tabs` for workspaces or `workspace Formal` to switch to Formal.
- Type `clear` to clear output; Copy output sends the transcript to clipboard.
- The View menu provides dock visibility and a Ctrl+backtick focus shortcut.
- This is NOT an unrestricted Linux shell.

Launch after updating:

```sh
git pull origin main
python3 -m pip install -e '.[native,formal,slang,security]'
wengold desktop --native /absolute/path/to/rtl-project
```

Validate with offscreen Qt:

```sh
QT_QPA_PLATFORM=offscreen python3 -m pytest -q tests/test_native_app.py tests/test_native_studio.py
```

## Choosing and automatically loading design + verification projects

Launching WENGOLD from the Linux application menu opens a native folder
chooser. Select the project root containing RTL and testbench sources.
Within the window, click **Open Project** or use **Ctrl+O** to switch
projects. **Rescan Files** reloads source files; the app checks for changed
files every 10 seconds, deferring re-indexing when the editor has unsaved edits.

The Overview explorer shows distinct groups for Design RTL, Verification/UVM,
Automation/Scripts, and Filelists. The same files appear in the editor source
picker; existing .sv, .v, .vhd, .pss, .py, .tcl and other supported scripts
can be viewed and saved with external-modification protection. Automation
scripts are never executed merely because they were discovered or opened.

The **Synthesis / PPA** workspace uses a real installed Yosys executable for
bounded single-source generic synthesis. It shows actual module/cell/wire
counts and a source/netlist digest; technology-mapped area, real STA,
power estimates and detailed schematic require separate EDA flows.
No simulated results are substituted for tool evidence.

Generated build directories, Python venvs and source-control metadata are
excluded from the HDL scanner. Projects exceeding 12,000 relevant sources
must be scoped down or loaded through a filtered filelist flow.

Recommended:

```sh
cd ~/wengold && git pull origin main
sh linux/install-desktop.sh
~/.local/bin/wengold desktop --native /absolute/path/to/your/project
```

Select the actual project folder rather than the entire home directory.
