"""Simulate a module and dump a waveform — the harness for the six-project run.

Given a project and a module name, this finds the file that defines it, writes a
testbench that drives it, runs Icarus Verilog, and returns the VCD path. The
testbench is generated from the module's own port list, because hand-writing one
per module across six projects is not the point — the point is a real waveform
from a real simulation.

Everything here is honest about what it does: the stimulus is a clock (if the
module has one), a reset (if it has one) and a counter on the remaining inputs.
That exercises the logic and produces a waveform worth looking at. It is not a
verification testbench and it proves nothing about the design.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

OSS = "/scratch/tmp/osscad/oss-cad-suite/bin"

# port direction + width, from a module header
_PORT = re.compile(
    r"^\s*(input|output|inout)\b\s*(?:wire|reg|logic|signed)?\s*"
    r"(?:\[([^\]]+)\])?\s*([A-Za-z_]\w*)", re.M)
_MODULE = re.compile(r"^\s*module\s+([A-Za-z_]\w*)", re.M)
_SKIP = re.compile(r"(?i)^(clk|clock|rst|reset|rst_n|resetn|rst_ni|rst_i|arst|areset)")


def find_module(root: Path, module: str) -> tuple[Path, str] | None:
    """Find the file defining `module`.

    `\\?` because a name with a dot in it is a legal *escaped identifier* —
    `module \\minerva.a (…)` is what Amaranth emits for a nested design, and
    searching for `module minerva.a` never matched it.
    """
    pattern = re.compile(rf"^\s*module\s+\\?{re.escape(module)}\b", re.M)
    for suffix in ("*.v", "*.sv"):
        for p in root.rglob(suffix):
            t = p.read_text(errors="replace")
            if pattern.search(t):
                return p, t
    return None


def ports_of(text: str, module: str) -> list[tuple[str, str, str]]:
    """(direction, width, name) for the named module.

    Splits the header on commas before parsing, so a one-line ANSI header
    (`module m(input clk, output q);`) works as well as the multi-line style most
    projects use — with `^` anchored per port the one-line form parsed to nothing.
    """
    # `\\?` for the escaped-identifier form (`module \minerva.a`), same as
    # find_module — without it this regex missed and the whole file was parsed as
    # if it were the module's header.
    m = re.search(rf"^\s*module\s+\\?{re.escape(module)}\b(.*?)\)\s*;", text,
                  re.M | re.S)
    body = (m.group(1) if m else text).lstrip("( \t\r\n")
    # drop a `#( ... )` parameter list. Left in, its parentheses keep the depth
    # counter above zero for the whole header, so no comma is ever split and the
    # module parses to a single port — which is what sync_fifo did.
    stripped = body.lstrip()
    if stripped.startswith("#"):
        stripped = stripped[1:].lstrip()
        if stripped.startswith("("):
            depth, i = 0, 0
            for i in range(len(stripped)):
                if stripped[i] == "(":
                    depth += 1
                elif stripped[i] == ")":
                    depth -= 1
                    if depth == 0:
                        break
            body = stripped[i + 1:].lstrip("( \t\r\n")
    # the opening `(` was stripped, so the depth counter must start balanced —
    # otherwise every comma sits at depth 1 and nothing is ever split
    chunks, depth, cur = [], 0, ""
    for ch in body:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            chunks.append(cur)
            cur = ""
        else:
            cur += ch
    chunks.append(cur)
    out = []
    for chunk in chunks:
        found = _PORT.search(" " + chunk.strip())
        if found:
            d, w, n = found.groups()
            out.append((d, w or "1", n))
    if out:
        return out

    # Non-ANSI (Verilog-95) header: the list is bare names and the directions are
    # declared in the body. Amaranth emits this form, so without it the generated
    # RTL parsed to zero ports and never simulated.
    names = [c.strip().split()[-1] for c in chunks if c.strip()]
    names = [n for n in names if re.fullmatch(r"[A-Za-z_]\w*", n)]
    # scan *this module's* body only. The whole file was scanned before, and on a
    # file with 51 modules that picked up port declarations from all of them —
    # including escaped identifiers from other designs.
    start = m.start() if m else 0
    end = text.find("endmodule", start)
    body = text[start:end if end > 0 else len(text)]
    seen = set()
    for d, w, n in _PORT.findall(body):
        if n in names and n not in seen:
            seen.add(n)
            out.append((d, w or "1", n))
    return out


def width_bits(spec: str) -> int:
    spec = spec.strip()
    if ":" in spec:
        hi, _, lo = spec.partition(":")
        try:
            return abs(int(hi.strip()) - int(lo.strip())) + 1
        except ValueError:
            return 1
    try:
        return max(1, int(spec))
    except ValueError:
        return 1


def make_tb(module: str, ports, clock: str | None, reset: str | None) -> str:
    decls, conns, drives = [], [], []
    for d, w, n in ports:
        width = f"[{width_bits(w) - 1}:0] " if width_bits(w) > 1 else ""
        if d == "input":
            decls.append(f"  reg {width}{n};")
            conns.append(f".{n}({n})")
            if n == clock:
                drives.append(f"  always #5 {n} = ~{n};")
            elif n == reset:
                drives.append(f"  initial begin {n} = 0; #42 {n} = 1; end")
            else:
                drives.append(f"  always #17 {n} = $random;")
        else:
            decls.append(f"  wire {width}{n};")
            conns.append(f".{n}({n})")
    init = [f"  {n} = 0;" for d, _w, n in ports if d == "input" and n != reset]
    # a module whose name is not a plain identifier (Amaranth emits `minerva.a`)
    # has to be instantiated through its escaped form: `\minerva.a dut (…)`
    ref = module if re.fullmatch(r"[A-Za-z_]\w*", module) else "\\" + module
    return "\n".join([
        f"module tb_wave;",
        *decls,
        f"  {ref} dut({', '.join(conns)});",
        *drives,
        "  initial begin",
        *init,
        '    $dumpfile("wave.vcd");',
        "    $dumpvars(0, tb_wave);",
        "    #600 $finish;",
        "  end",
        "endmodule",
    ])


def simulate(root: Path, module: str, work: Path, incdirs: list[Path]) -> dict:
    found = find_module(root, module)
    if not found:
        # not a Verilog module — try VHDL, where the unit is an entity. WENGOLD's
        # graph reads VHDL, so the waveform side has to as well, or a VHDL project
        # indexes fine and then reports nothing but "not found".
        return simulate_vhdl(root, module, work)
    return _simulate_verilog(root, module, work, incdirs, found)


def _simulate_verilog(root, module, work, incdirs, found) -> dict:
    path, text = found
    ports = ports_of(text, module)
    if not ports:
        return {"module": module, "ok": False, "why": "no ports parsed"}
    ins = [n for d, _w, n in ports if d == "input"]
    clock = next((n for n in ins if re.search(r"(?i)clk|clock", n)), None)
    reset = next((n for n in ins if _SKIP.match(n) and n != clock), None)

    work.mkdir(parents=True, exist_ok=True)
    # some modules carry their own $dumpfile call — rustdv_fifo's FIFO dumps to
    # `build/fifo_waveform.vcd`, and vvp aborts with a hard error when that
    # directory does not exist. Create whatever paths the source asks for.
    for want in re.findall(r"\$dumpfile\s*\(\s*\"([^\"]+)\"", text):
        (work / want).parent.mkdir(parents=True, exist_ok=True)
    (work / "tb.v").write_text(make_tb(module, ports, clock, reset))
    vvp = work / "sim.vvp"
    inc = [f"-I{d}" for d in incdirs]
    # `-s tb_wave` forces the generated testbench to be the top module. Without it
    # a testbench that happens to live in the same file as the module under test
    # is elaborated too, and its own `$finish` ends the run before ours dumps.
    cmd = [f"{OSS}/iverilog", "-g2012", "-s", "tb_wave", "-o", str(vvp), *inc,
           str(path), str(work / "tb.v")]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return {"module": module, "ok": False, "why": "compile timed out"}
    if r.returncode != 0:
        first = next((ln for ln in r.stderr.splitlines() if "error" in ln.lower()),
                     r.stderr.strip().splitlines()[:1] or ["compile failed"])
        return {"module": module, "ok": False, "why": f"compile: {first[:110]}",
                "file": str(path.relative_to(root))}
    r2 = subprocess.run([f"{OSS}/vvp", str(vvp)], capture_output=True, text=True,
                        cwd=work, timeout=120)
    vcd = work / "wave.vcd"
    if not vcd.exists():
        # the module's own $dumpfile wins the race — VCD allows one file, and the
        # first call takes it — so the data may be at the path the source asked
        # for rather than ours. Take whatever was written.
        found = sorted(work.rglob("*.vcd"), key=lambda p: p.stat().st_size,
                       reverse=True)
        if not found:
            return {"module": module, "ok": False, "why": "no VCD produced"}
        vcd = found[0]
    return {"module": module, "ok": True, "vcd": str(vcd),
            "file": str(path.relative_to(root)), "inputs": len(ins),
            "outputs": len(ports) - len(ins), "clock": clock}


# ---- VHDL ------------------------------------------------------------------
_ENTITY = re.compile(r"^\s*entity\s+([A-Za-z_]\w*)\s+is", re.M | re.I)
_PORT_SECTION = re.compile(r"\bport\s*\((.*?)\)\s*;", re.S | re.I)
_VDECL = re.compile(
    r"([A-Za-z_]\w*)\s*:\s*(in|out|inout)\s+"
    r"(std_logic_vector\s*\(\s*([^)]*?)\s*\)|std_logic|std_ulogic|"
    r"unsigned\s*\(\s*([^)]*?)\s*\)|signed\s*\(\s*([^)]*?)\s*\)|integer)",
    re.I)


def find_entity(root: Path, entity: str) -> tuple[Path, str] | None:
    pattern = re.compile(rf"^\s*entity\s+{re.escape(entity)}\s+is", re.M | re.I)
    for suffix in ("*.vhd", "*.vhdl"):
        for p in root.rglob(suffix):
            t = p.read_text(errors="replace")
            if pattern.search(t):
                return p, t
    return None


def _balanced(text: str, keyword: str) -> str:
    r"""The text inside `keyword ( ... )`, counting parentheses.

    A non-greedy `.*?\)` stops at the first `)`, which in a port clause is inside
    the first vector — `std_logic_vector(31 downto 0);` — so the clause was cut
    off there and every vector port after it parsed as a single bit.
    """
    m = re.search(rf"\b{keyword}\s*\(", text, re.I)
    if not m:
        return ""
    depth, start = 0, m.end()
    for i in range(m.end() - 1, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return text[start:i]
    return ""


def vhdl_ports(text: str) -> list[tuple[str, str, str]]:
    """(name, direction, width_span) from an entity's port clause."""
    clause = _balanced(text, "port")
    if not clause:
        return []
    body = re.sub(r"--[^\n]*", "", clause)
    out = []
    for decl in body.split(";"):
        d = _VDECL.search(decl)
        if not d:
            continue
        name, direction = d.group(1), d.group(2)
        kind = (d.group(3) or "").lower()
        if "vector" in kind or "unsigned" in kind or "signed" in kind:
            span = d.group(4) or d.group(5) or d.group(6) or ""
            out.append((name, direction, span.strip()))
        else:
            out.append((name, direction, "1"))
    return out


def vhdl_width(span: str) -> int:
    m = re.search(r"(\d+)\s+(?:downto|to)\s+(\d+)", span or "")
    return abs(int(m.group(1)) - int(m.group(2))) + 1 if m else 1


_GENERIC_SECTION = re.compile(r"\bgeneric\s*\((.*?)\)\s*;", re.S | re.I)


def vhdl_generics(text: str) -> list[tuple[str, str]]:
    """(name, default) from an entity's generic clause.

    A generic left unmapped makes GHDL refuse to elaborate the design, which is
    how lxp32's ALU failed after its 36 files had analysed cleanly.
    """
    clause = _balanced(text, "generic")
    if not clause:
        return []
    body = re.sub(r"--[^\n]*", "", clause)
    out = []
    for decl in body.split(";"):
        d = re.match(r"\s*([A-Za-z_]\w*)\s*:\s*([^:=]+?)\s*(?::=\s*(.+))?$",
                     decl.strip(), re.S)
        if not d:
            continue
        name, kind, default = d.group(1), d.group(2).strip().lower(), d.group(3)
        if default:
            out.append((name, default.strip()))
            continue
        # a required generic with no default still has to be supplied. lxp32's ALU
        # declares `DIVIDER_EN: boolean;` with no default, and leaving it unmapped
        # stops GHDL elaborating the design after all 36 files analysed cleanly.
        if "boolean" in kind:
            value = "true"
        elif "string" in kind:
            value = '""'
        elif "time" in kind:
            value = "10 ns"
        elif any(k in kind for k in ("integer", "natural", "positive")):
            value = "1"
        else:
            continue
        out.append((name, value))
    return out


def make_vhdl_tb(entity: str, ports, generics=()) -> str:
    sig, conn, drive = [], [], []
    for name, direction, span in ports:
        width = vhdl_width(span)
        typ = "std_logic" if width == 1 else f"std_logic_vector({width - 1} downto 0)"
        if direction.lower() == "in":
            default = "'0'" if width == 1 else "(others => '0')"
            sig.append(f"  signal {name} : {typ} := {default};")
            conn.append(f"{name} => {name}")
            low = name.lower()
            if re.search(r"clk|clock", low):
                drive.append(f"  {name} <= not {name} after PERIOD / 2;")
            elif re.search(r"rst|reset", low):
                drive.append(f"  {name} <= '0', '1' after 42 ns;")
            elif width == 1:
                drive.append(f"  {name} <= not {name} after 17 ns;")
            else:
                drive.append(f"  {name} <= std_logic_vector(unsigned({name}) + 1) "
                             f"after 17 ns;")
        else:
            sig.append(f"  signal {name} : {typ};")
            conn.append(f"{name} => {name}")
    gmap = ""
    if generics:
        gmap = ("generic map (" + ", ".join(f"{n} => {v}" for n, v in generics)
                + ") ")
    return "\n".join([
        "library ieee;",
        "use ieee.std_logic_1164.all;",
        "use ieee.numeric_std.all;",
        "entity tb_wave is end entity;",
        "architecture sim of tb_wave is",
        *sig,
        "  constant PERIOD : time := 10 ns;",
        "begin",
        f"  dut: entity work.{entity} {gmap}port map ({', '.join(conn)});",
        *drive,
        "  stim: process begin",
        "    wait for 600 ns;",
        "    std.env.finish;",
        "  end process;",
        "end architecture;",
    ])


def simulate_vhdl(root: Path, entity: str, work: Path) -> dict:
    found = find_entity(root, entity)
    if not found:
        return {"module": entity, "ok": False, "why": "not found"}
    path, text = found
    ports = vhdl_ports(text)
    if not ports:
        return {"module": entity, "ok": False, "why": "no ports parsed",
                "file": str(path.relative_to(root))}
    work.mkdir(parents=True, exist_ok=True)
    tb = work / "tb.vhd"
    tb.write_text(make_vhdl_tb(entity, ports, vhdl_generics(text)))

    # analyse every source, in passes: a file referring to an entity not yet
    # analysed fails the first pass and succeeds on a later one
    pending = sorted(str(p) for p in root.rglob("*.vhd"))
    analysed, passes = [], 0
    while pending and passes < 6:
        passes += 1
        still = []
        for src in pending:
            r = subprocess.run([f"{OSS}/ghdl", "-a", "--std=08",
                                f"--workdir={work}", src],
                               capture_output=True, text=True, timeout=120)
            (analysed if r.returncode == 0 else still).append(src)
        if len(still) == len(pending):
            break
        pending = still
    r = subprocess.run([f"{OSS}/ghdl", "-a", "--std=08", f"--workdir={work}",
                        str(tb)], capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        first = next((ln for ln in r.stderr.splitlines() if "error" in ln.lower()),
                     "analyse failed")
        return {"module": entity, "ok": False, "why": f"ghdl: {first[:110]}",
                "file": str(path.relative_to(root)), "analysed": len(analysed)}
    r = subprocess.run([f"{OSS}/ghdl", "-e", "--std=08", f"--workdir={work}",
                        "-o", str(work / "sim"), "tb_wave"],
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        return {"module": entity, "ok": False, "why": "ghdl: elaborate failed",
                "file": str(path.relative_to(root)), "analysed": len(analysed)}
    subprocess.run([f"{OSS}/ghdl", "-r", "--std=08", f"--workdir={work}",
                    str(work / "sim"), f"--vcd={work / 'wave.vcd'}",
                    "--stop-time=600ns"], capture_output=True, text=True,
                   cwd=work, timeout=120)
    if not (work / "wave.vcd").exists():
        return {"module": entity, "ok": False, "why": "no VCD produced",
                "file": str(path.relative_to(root)), "analysed": len(analysed)}
    ins = sum(1 for _n, d, _s in ports if d.lower() == "in")
    return {"module": entity, "ok": True, "vcd": str(work / "wave.vcd"),
            "file": str(path.relative_to(root)), "inputs": ins,
            "outputs": len(ports) - ins, "language": "vhdl",
            "analysed": len(analysed),
            "clock": next((n for n, d, _s in ports if d.lower() == "in"
                           and re.search(r"clk|clock", n.lower())), None)}


if __name__ == "__main__":
    root, module, work = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    inc = [Path(a) for a in sys.argv[4:]]
    print(simulate(root, module, work, inc))
