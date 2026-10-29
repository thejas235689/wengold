# Installing WENGOLD on Linux

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
