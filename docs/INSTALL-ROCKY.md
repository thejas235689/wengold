# Installing WENGOLD on Rocky Linux

## If installing tools is failing, you do not need them

The graph, the kernel, the front-ends and the CLI are **standard library only**. No
pip, no root, no package manager, nothing written outside the checkout:

```bash
git clone https://github.com/thejas235689/wengold.git
cd wengold
sh wengold.sh --version
sh wengold.sh doctor
sh wengold.sh index path/to/rtl
```

The only requirement is **Python 3.11 or newer**. `wengold.sh` finds it for you
(trying `python3.13`, `python3.12`, `python3.11`, then `python3`) and says what to
install if none is new enough.

```bash
sh wengold.sh --where      # which interpreter, and which extras are present
```

Everything below is optional. pyslang gives a real SystemVerilog parse instead of
the bounded regex fallback; z3 enables the formal loop; numpy enables `learn` and
`spec-from-text`; PyQt6 enables the native window. **None of them is required to
run wengold**, and each one's absence is reported as what it costs rather than as a
failure.

---

Rocky is RHEL-family, so the `.deb` in `dist/` is **not** for you — it is Debian
packaging. The full installer works too: `linux/install.sh` is plain POSIX shell and
uses no package manager at all, so it runs unchanged on Rocky. It adds a launcher,
a menu entry and an icon; `wengold.sh` adds none of those and needs nothing.

There are two things that differ from a Debian box: **the Python version** and **the
Qt system libraries**.

## The Python version is the only real trap

`pyproject.toml` requires **Python 3.11 or newer**, and the installer runs whatever
`python3` it finds first on `PATH`.

| Rocky | system `python3` | what to do |
| --- | --- | --- |
| 10 | 3.12 | nothing — the default works |
| 9 | **3.9** | install a newer one and shim it (below) |

Check first:

```bash
python3 -V
```

If it prints 3.11 or newer, skip to **Install**.

### Rocky 9: get a newer Python without breaking dnf

Do **not** replace the system `python3`. On Rocky 9, `dnf` itself runs on Python
3.9 — repointing `python3` at 3.11 breaks your package manager.

Install the newer interpreter alongside it, then put a `python3` shim in front of
it *for the install only*:

```bash
sudo dnf install -y python3.11 python3.11-pip

mkdir -p ~/.local/bin-py
ln -sf /usr/bin/python3.11 ~/.local/bin-py/python3

PATH="$HOME/.local/bin-py:$PATH" python3 -V     # should print 3.11.x
```

The installer honours that shim because it resolves `python3` from `PATH` — verified,
not assumed.

## Install

```bash
git clone https://github.com/thejas235689/wengold.git
cd wengold

# Rocky 9 only — omit this prefix on Rocky 10
PATH="$HOME/.local/bin-py:$PATH" sh linux/install.sh

# Rocky 10
sh linux/install.sh
```

Everything lands under `~/.local`, with no root and no package manager:

```
~/.local/bin/wengold                              the launcher
~/.local/share/wengold/                           the package
~/.local/share/applications/wengold.desktop       menu entry
~/.local/share/icons/hicolor/scalable/apps/       icon
```

The installer verifies itself: it runs the launcher it just wrote and fails loudly
if `wengold --version` does not answer. If it printed `verified: wengold <version> —
launcher answers --version`, the install is good.

Add it to your `PATH` if the installer tells you to:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

```bash
wengold --version
wengold doctor
```

## The native window (optional)

The CLI works with no Qt at all. The desktop window needs PyQt6 plus the Qt system
libraries, which have different names on RHEL than on Debian:

```bash
sudo dnf install -y mesa-libGL libxkbcommon-x11 \
    xcb-util-wm xcb-util-image xcb-util-keysyms xcb-util-renderutil \
    fontconfig

python3 -m pip install --user PyQt6
```

Then `wengold desktop` opens the native window, and the menu entry appears under
**Development**. Without PyQt6, `wengold desktop` falls back to a browser window —
that is a fallback, not a failure.

## Optional extras

```bash
# a real SystemVerilog parse instead of the bounded regex fallback
python3 -m pip install --user pyslang z3-solver

# the local model client (Sarvam-M is 24B — needs ~16 GB)
python3 -m pip install --user torch transformers
python3 tools/verify-real-model.py
```

`wengold doctor` tells you which of these it found and, more usefully, which it did
not — a missing `pyslang` is reported as *"an under-estimate, not the design"*
rather than as a low block count.

## Uninstall

```bash
sh linux/uninstall.sh
```

It removes exactly the four things `install.sh` created and leaves your project data
and `.tof/` directories alone.

## What is Rocky-specific and what is not

| | |
| --- | --- |
| `linux/install.sh` | distro-agnostic POSIX shell — works as-is |
| `.deb` in `dist/` | Debian only — not used here |
| Python ≥ 3.11 | the one version trap (Rocky 9) |
| Qt library names | `dnf`, not `apt` — listed above |
| `pyslang`, `z3-solver`, `numpy` | manylinux wheels — install unchanged |

Verified on this machine: the installer, its self-check, the launcher, `--version`,
subcommands, the desktop entry, and a clean uninstall. **Not verified on Rocky
itself** — the package names above are RHEL 9's, and if `dnf` disagrees with one of
them it will say so at install time rather than silently doing nothing.
