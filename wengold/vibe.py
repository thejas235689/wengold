"""Vibe coding, with the loop closed.

"Describe it in words and get RTL" is only worth having if the RTL that comes out
has been *checked*. This module chains the pieces that already exist and adds the
one thing missing:

    text or spec ──▶ spec ──▶ RTL ──▶ generated testbench ──▶ iverilog ──▶ verdict

The last two steps are the point. A generated block is written to, read back, and
the value must come out; reset values are checked; a read-only register must not
change when written. If any of that fails, you get `fail` and the line — not a
cheerful summary.

**What this can and cannot do.** The text front-end reads a narrow register-block
grammar (`spec_text.py`) and scores 0% on held-out vocabulary. So a sentence that
is not in that grammar is refused with the reason rather than turned into RTL that
looks plausible. Anything the generator cannot emit — a state machine, a pipeline,
an interface — is refused too, by `generate`.

The value is not that it understands English. It is that **nothing reaches you
unverified**: the block is simulated before you see it.
"""
from __future__ import annotations

from pathlib import Path

__all__ = ["vibe", "render"]

CLK, RST = "clk_i", "rst_ni"
REG_PORTS = ("reg_wr_i", "reg_rd_i", "reg_addr_i", "reg_wdata_i", "reg_rdata_o")


def _load_spec(text_or_path: str, module: str | None = None) -> tuple[dict, str]:
    """A spec from a YAML/JSON path, or from a sentence. Returns (spec, source)."""
    p = Path(text_or_path)
    if p.exists() and p.suffix.lower() in (".yaml", ".yml", ".json"):
        import yaml
        return yaml.safe_load(p.read_text()), "file"

    # The text front-end is a grammar reader, not a language model: it reads the
    # register-block grammar it was trained on and refuses anything else. The
    # model is cached on disk, so only the first use pays for training.
    from .spec_frontend import draft_spec, load_or_train

    model, vocab_list = load_or_train()
    d = draft_spec(text_or_path, model, vocab_list)
    if not d.ok:
        raise ValueError(d.error)
    from .spec_frontend import to_module_spec
    return to_module_spec(dict(d.spec), d.spec.get("register", "drafted")), "text"


def _masks(reg) -> dict:
    """Bit masks by access mode, plus the reset value.

    `w1c` is the one that is easy to get wrong: writing 1 **clears** the bit, so a
    register that clears on write must NOT read back what was written. Checking it
    as `rw` reported a correct design as broken — which is the same class of error
    as passing a broken one.
    """
    out = {"rw": 0, "w1c": 0, "ro": 0, "reset": 0, "mask": 0}
    for f in getattr(reg, "fields", []):
        hi, lo = int(f.hi), int(f.lo)
        m = ((1 << (hi - lo + 1)) - 1) << lo
        access = str(f.access).lower()
        out["mask"] |= m
        out["reset"] |= (int(f.reset) << lo) & m
        if access in ("rw",):
            out["rw"] |= m
        elif access in ("w1c",):
            out["w1c"] |= m
        else:
            out["ro"] |= m
    return out


def _field_mask(reg) -> tuple[int, int]:
    """(mask, reset) for a register, from its fields."""
    mask = reset = 0
    for f in getattr(reg, "fields", []):
        hi, lo = int(f.hi), int(f.lo)
        m = ((1 << (hi - lo + 1)) - 1) << lo
        mask |= m
        reset |= (int(f.reset) << lo) & m
    return mask, reset


def make_testbench(spec: dict, all_ports=None) -> str:
    """A self-checking testbench for a generated register block.

    Checks, in order:
      * every register reads back its reset value after reset
      * every `rw` register accepts a write and returns what was written
      * every `ro` register ignores a write
    """
    module = spec.name
    # `all_ports` comes from the generator's ModuleSpec and includes the register
    # bus it adds. Reading the raw spec's port list instead produced a testbench
    # with no register ports at all — which compiled, ran, and checked nothing.
    # without an explicit port list, fall back to the spec's own ports — a block
    # with no register interface is checked for undriven outputs instead
    source_ports = all_ports if all_ports else getattr(spec, "ports", [])
    ports = [{"name": p.name, "dir": p.direction, "width": p.width}
             for p in source_ports]
    regs = list(getattr(spec, "registers", []) or [])

    decls, conns = [], []
    for p in ports:
        name, width = p["name"], int(p.get("width", 1))
        rng = "" if width == 1 else f"[{width - 1}:0] "
        if p["dir"] == "input":
            init = " = 0"
            if name == CLK:
                init = " = 0"
            decls.append(f"  logic {rng}{name}{init};")
            conns.append(f".{name}({name})")
        else:
            decls.append(f"  logic {rng}{name};")
            conns.append(f".{name}({name})")

    # A block need not have a register interface. The timer spec has none, and
    # emitting write/read tasks for ports that do not exist is a testbench that
    # cannot compile — which reads as "the generated RTL is broken".
    names = {p["name"] for p in ports}
    has_bus = {"reg_wr_i", "reg_rd_i", "reg_addr_i", "reg_wdata_i",
               "reg_rdata_o"} <= names
    regs = regs if has_bus else []

    body = []
    if not has_bus:
        # no bus: at least require that every output is defined after reset, so an
        # un-driven port is caught rather than passing silently as X
        for p_ in ports:
            if p_["dir"] == "output":
                n = p_["name"]
                body.append(f'    if (^{n} === 1\'bx)')
                body.append(f'      $fatal(1, "output {n} is X after reset");')
    if regs:
        body.append("    // reset values")
        for r in regs:
            mask, reset = _field_mask(r)
            addr = int(r.addr)
            body.append(f"    rd(32'h{addr:02x}, d);")
            body.append(f"    if ((d & 32'h{mask:08x}) !== 32'h{reset & mask:08x})")
            body.append(f'      $fatal(1, "{r.name} reset: expected %08x got %08x",'
                        f' 32\'h{reset & mask:08x}, d & 32\'h{mask:08x});')

        body.append("    // writes and read-backs")
        for r in regs:
            m = _masks(r)
            addr = int(r.addr)
            name = r.name

            # readable/writable: write a pattern, expect it back
            if m["rw"]:
                pat = (m["rw"] & 0x5A5A5A5A) or m["rw"]
                body += [f"    wr(32'h{addr:02x}, 32'h{pat:08x});",
                         f"    rd(32'h{addr:02x}, d);",
                         f"    if ((d & 32'h{m['rw']:08x}) !== 32'h{pat:08x})",
                         f'      $fatal(1, "{name} rw write/read: expected %08x got '
                         f'%08x", 32\'h{pat:08x}, d & 32\'h{m["rw"]:08x});']

            # write-1-to-clear: writing 1s must clear the bits, not store them
            if m["w1c"]:
                body += [f"    wr(32'h{addr:02x}, 32'h{m['w1c']:08x});",
                         f"    rd(32'h{addr:02x}, d);",
                         f"    if ((d & 32'h{m['w1c']:08x}) !== 32'h0)",
                         f'      $fatal(1, "{name} is write-1-to-clear but did not '
                         f'clear: %08x", d & 32\'h{m["w1c"]:08x});']

            # read-only: a write must not change it
            if m["ro"]:
                body += [f"    wr(32'h{addr:02x}, 32'h{m['ro']:08x});",
                         f"    rd(32'h{addr:02x}, d);",
                         f"    if ((d & 32'h{m['ro']:08x}) !== "
                         f"32'h{m['reset'] & m['ro']:08x})",
                         f'      $fatal(1, "{name} is read-only but changed: %08x", '
                         f'd & 32\'h{m["ro"]:08x});']

    tasks = ""
    if has_bus:
        tasks = (f"  task automatic wr(input [31:0] a, input [31:0] v);\n"
                 f"    @(posedge {CLK}); reg_wr_i <= 1; reg_addr_i <= a;"
                 f" reg_wdata_i <= v;\n"
                 f"    @(posedge {CLK}); reg_wr_i <= 0;\n  endtask\n\n"
                 f"  task automatic rd(input [31:0] a, output [31:0] v);\n"
                 f"    @(posedge {CLK}); reg_rd_i <= 1; reg_addr_i <= a;\n"
                 f"    @(posedge {CLK}); reg_rd_i <= 0; #1; v = reg_rdata_o;\n"
                 f"  endtask")

    return f"""// Generated by WENGOLD — self-checking testbench for {module}.
// Do not edit: regenerate from the spec.
module {module}_tb;
{chr(10).join(decls)}
  logic [31:0] d;

  {module} dut({", ".join(conns)});

  always #5 {CLK} = ~{CLK};

{tasks}

  initial begin
    repeat(3) @(posedge {CLK});
    {RST} <= 1;
    #1;
{chr(10).join(body) if body else '    // no registers to check'}
    $display("PASSED");
    $finish;
  end
endmodule
"""


def vibe(text_or_spec: str, out: str = ".", tools: str | None = None,
         module: str | None = None) -> dict:
    """Run the whole loop. Returns a report dict; never raises on a bad spec."""
    from .agent.runners import ToolRunner, Toolchain
    from .generate.conform import check as conform_check  # noqa: F401

    outdir = Path(out)
    rec: dict = {"input": text_or_spec, "out": str(outdir)}

    # ---- 1. spec -------------------------------------------------------
    try:
        spec, source = _load_spec(text_or_spec, module)
    except Exception as exc:
        rec["stage"] = "spec"
        rec["ok"] = False
        rec["error"] = (f"could not read a spec from that: {exc}. The text "
                        f"front-end reads a register-block grammar; anything "
                        f"outside it is refused rather than guessed.")
        return rec
    rec["spec_source"] = source
    rec["module"] = spec.name if hasattr(spec, "name") else spec.get("module")

    # ---- 2. RTL --------------------------------------------------------
    # The generator has its own strict spec loader; a spec it cannot emit is
    # refused there rather than half-emitted here.
    from .generate.emit import emit_rtl
    from .generate.spec import SpecError, load_spec

    outdir.mkdir(parents=True, exist_ok=True)
    # a dict means it came from a file; anything else is already a ModuleSpec.
    # Keying on "registers" sent a register-less spec (the timer) down the wrong
    # branch, where emit_rtl got a dict.
    if isinstance(spec, dict):
        # a YAML/JSON spec: the generator has its own strict loader
        tmp = outdir / ".spec.yaml"
        import yaml as _yaml
        tmp.write_text(_yaml.safe_dump(spec))
        try:
            mspec = load_spec(str(tmp))
        except SpecError as exc:
            rec["stage"] = "generate"
            rec["ok"] = False
            rec["error"] = (f"{exc}. The generator emits register blocks: assigns, "
                            f"registers, one clocked always_ff. A state machine, a "
                            f"pipeline or an interface is refused rather than dropped.")
            return rec
        try:
            tmp.unlink()
        except OSError:
            pass
    else:
        # a text draft is already a ModuleSpec
        mspec = spec

    # The header cites where the spec came from. After loading through a temporary
    # file it named the temp path, which the reader never wrote and cannot find.
    if getattr(mspec, "source", "").endswith(".spec.yaml"):
        mspec.source = (text_or_spec if source == "file"
                        else f"the sentence: {text_or_spec[:60]}")
    rtl = emit_rtl(mspec)
    rec["module"] = mspec.name

    sv = outdir / f"{mspec.name}.sv"
    sv.write_text(rtl)

    tb = outdir / f"{mspec.name}_tb.sv"
    tb.write_text(make_testbench(mspec, mspec.all_ports))
    rec["files"] = [str(sv), str(tb)]

    # ---- 3. simulate ---------------------------------------------------
    from .cli import _collect
    from .graph.builder import GraphBuilder
    from .kernel.validity import Result

    g = GraphBuilder().build_from_files(_collect(str(outdir)), backend="auto")
    rid = f"{mspec.name}_sim"
    results = {rid: Result(rid, "sim", depends_on={mspec.name})}
    tc = Toolchain(tools)
    runner = ToolRunner(g, results, str(outdir), toolchain=tc)
    outcome = runner(rid, "sim")

    rec["stage"] = "simulate"
    rec["tool"] = outcome["tool"]
    rec["outcome"] = outcome["outcome"]
    rec["ok"] = outcome["outcome"] == "pass"
    rec["note"] = outcome["note"]
    rec["log"] = outcome.get("log", "")[-2000:]
    return rec


def render(rec: dict) -> str:
    lines = []
    name = rec.get("module") or "?"
    if not rec.get("ok"):
        lines.append(f"  could not build {name}")
        lines.append(f"    stage: {rec.get('stage')}")
        if rec.get("error"):
            lines.append(f"    {rec['error']}")
        if rec.get("note"):
            lines.append(f"    {rec['note']}")
        if rec.get("log"):
            for l in rec["log"].splitlines()[:6]:
                lines.append(f"      {l[:110]}")
        return "\n".join(lines)

    lines.append(f"  {name}  —  {rec['outcome']} ({rec['tool']})")
    lines.append(f"    spec from: {rec.get('spec_source')}")
    for f in rec.get("files", []):
        lines.append(f"    wrote {f}")
    lines.append(f"    {rec['note']}")
    return "\n".join(lines)
