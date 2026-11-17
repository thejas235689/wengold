"""RTL hierarchy and port-connectivity extraction from an elaborated Yosys JSON netlist.

Yosys is the elaborator. This module preserves hierarchy (does not run flatten),
maps instance ports to parent nets, and exposes source attributes when present.
The resulting graph is logical connectivity, not placement or routed geometry.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


MAX_INSTANCES = 2000
MAX_PORTS_PER_INSTANCE = 512


def _source_location(attributes: dict[str, Any] | None) -> dict[str, Any] | None:
    raw = (attributes or {}).get("src")
    if raw is None:
        return None
    value = str(raw)
    match = re.match(r"(.+?):(\d+)(?:\.(\d+))?", value)
    if not match:
        return {"raw": value}
    return {"file": match.group(1), "line": int(match.group(2)),
            "column": int(match.group(3) or 1), "raw": value}


def _bit_names(module: dict[str, Any]) -> dict[int, list[str]]:
    result: dict[int, list[str]] = {}
    for name, net in (module.get("netnames") or {}).items():
        for bit in net.get("bits", []):
            if isinstance(bit, int):
                result.setdefault(bit, []).append(name)
    for name, port in (module.get("ports") or {}).items():
        for bit in port.get("bits", []):
            if isinstance(bit, int):
                result.setdefault(bit, []).append(name)
    return result


def build_rtl_hierarchy(netlist: dict[str, Any], *, top: str = "",
                        max_instances: int = MAX_INSTANCES) -> dict[str, Any]:
    """Expand module instances and connect child ports to their parent nets."""
    modules = netlist.get("modules") or {}
    if not modules:
        raise ValueError("Yosys JSON contains no modules")
    if top and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", top):
        raise ValueError("Top module must be a simple Verilog/SystemVerilog identifier")
    if top:
        if top not in modules:
            raise ValueError(f"Top module {top!r} was not found in the elaborated design")
    else:
        marked = [name for name, item in modules.items()
                  if str((item.get("attributes") or {}).get("top", "0")).strip("0") == "1"]
        top = marked[0] if marked else next(iter(modules))

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    warnings: list[str] = []
    truncated = False

    def walk(module_name: str, instance_path: str, parent_module: dict[str, Any] | None = None,
             instance_cell: dict[str, Any] | None = None) -> None:
        nonlocal truncated
        if len(nodes) >= max_instances:
            truncated = True
            return
        module = modules[module_name]
        node = {
            "id": instance_path,
            "module": module_name,
            "source": _source_location((instance_cell or {}).get("attributes"))
                      or _source_location(module.get("attributes")),
            "ports": [],
        }
        nodes.append(node)
        if parent_module is not None and instance_cell is not None:
            parent_names = _bit_names(parent_module)
            child_ports = module.get("ports") or {}
            connections = instance_cell.get("connections") or {}
            for port_name, child_port in child_ports.items():
                parent_bits = connections.get(port_name, [])
                child_bits = child_port.get("bits", [])
                direction = child_port.get("direction", "inout")
                for index, (parent_bit, child_bit) in enumerate(zip(parent_bits, child_bits)):
                    parent_candidates = parent_names.get(parent_bit, []) if isinstance(parent_bit, int) else []
                    child_candidates = _bit_names(module).get(child_bit, []) if isinstance(child_bit, int) else []
                    parent_net = parent_candidates[0] if parent_candidates else str(parent_bit)
                    child_net = child_candidates[0] if child_candidates else str(child_bit)
                    edges.append({
                        "from": instance_path.rsplit(".", 1)[0] + "." + parent_net,
                        "to": instance_path + "." + port_name,
                        "instance": instance_path, "port": port_name,
                        "direction": direction, "bit_index": index,
                        "parent_bit": parent_bit, "child_bit": child_bit,
                    })
                node["ports"].append({
                    "name": port_name, "direction": direction,
                    "width": len(child_bits),
                    "parent_net": (parent_names.get(parent_bits[0], [str(parent_bits[0])])[0]
                                   if parent_bits and isinstance(parent_bits[0], int) else
                                   (str(parent_bits[0]) if parent_bits else "")),
                    "source": node["source"],
                })
        else:
            for port_name, port in (module.get("ports") or {}).items():
                node["ports"].append({
                    "name": port_name, "direction": port.get("direction", "inout"),
                    "width": len(port.get("bits", [])), "parent_net": port_name,
                    "source": node["source"],
                })

        cells = module.get("cells") or {}
        for cell_name, cell in sorted(cells.items()):
            child_type = cell.get("type", "")
            if child_type not in modules:
                continue
            child_path = instance_path + "." + cell_name
            walk(child_type, child_path, module, cell)
            if truncated:
                return

    walk(top, top)
    return {
        "top": top, "nodes": nodes, "edges": edges,
        "instance_count": len(nodes), "connection_count": len(edges),
        "truncated": truncated, "warnings": warnings,
        "qualification": "Yosys elaborated hierarchy and port connections; not physical layout",
    }


def elaborate_with_yosys(project_root: str | Path, sources: list[str | Path], *,
                         top: str, yosys: str = "yosys", frontend: str = "yosys",
                         slang_plugin: str = "slang", sv_standard: str = "1800-2017",
                         slang_unroll_limit: int = 4096,
                         include_dirs: list[str | Path] | None = None,
                         defines: list[str] | None = None,
                         timeout_seconds: int = 300) -> dict[str, Any]:
    """Elaborate hierarchy through yosys-slang or the legacy Yosys SV frontend."""
    if frontend not in {"slang", "yosys"}:
        raise ValueError("frontend must be 'slang' or 'yosys'")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", top):
        raise ValueError("Top module must be a simple Verilog/SystemVerilog identifier")
    if frontend == "slang" and sv_standard not in {"1800-2017", "1800-2023", "latest"}:
        raise ValueError("Unsupported Slang SystemVerilog standard")
    if frontend == "slang" and (not isinstance(slang_unroll_limit, int)
                                or slang_unroll_limit < 1 or slang_unroll_limit > 100000):
        raise ValueError("slang_unroll_limit must be an integer from 1 to 100000")
    executable = shutil.which(yosys)
    if not executable:
        raise RuntimeError("Yosys executable not found. Install Yosys or set its executable path.")
    root = Path(project_root).resolve()
    if not sources:
        raise ValueError("Select at least one SystemVerilog/Verilog source file")
    resolved = []
    for source in sources:
        path = (root / source).resolve() if not Path(source).is_absolute() else Path(source).resolve()
        if root not in path.parents and path != root:
            raise ValueError(f"Source escapes project root: {source}")
        if not path.is_file() or path.suffix.lower() not in {".sv", ".v"}:
            raise ValueError(f"Not a readable Verilog/SystemVerilog source: {source}")
        resolved.append(path)
    output = root / ".wengold" / "rtl_hierarchy.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    incdirs = []
    for directory in include_dirs or []:
        path = (root / directory).resolve() if not Path(directory).is_absolute() else Path(directory).resolve()
        if root not in path.parents and path != root:
            raise ValueError(f"Include directory escapes project root: {directory}")
        if not path.is_dir():
            raise ValueError(f"Include directory does not exist: {directory}")
        incdirs.append(path)
    macro_args = []
    for define in defines or []:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:=[^\s;]+)?", define):
            raise ValueError(f"Invalid preprocessor define: {define}")
        macro_args.append("-D" + define)
    if frontend == "slang":
        # Load the plugin as its own Yosys command before invoking read_slang.
        script = ["plugin -i " + slang_plugin]
        read_cmd = ["read_slang --top " + top + " --std " + sv_standard
                    + " --keep-hierarchy --unroll-limit " + str(slang_unroll_limit)]
        read_cmd.extend("-I " + str(path) for path in incdirs)
        read_cmd.extend(macro_args)
        read_cmd.extend(str(path) for path in resolved)
        script.append(" ".join(read_cmd))
    else:
        read_cmd = ["read_verilog -sv"]
        read_cmd.extend("-I" + str(path) for path in incdirs)
        read_cmd.extend(macro_args)
        read_cmd.extend(str(path) for path in resolved)
        script = [" ".join(read_cmd)]
    script.extend(["hierarchy -check -top " + top,
                   "proc", "write_json " + str(output)])
    completed = subprocess.run(
        [executable, "-Q", "-q", "-p", "; ".join(script)],
        cwd=root, capture_output=True, text=True, timeout=timeout_seconds, check=False)
    if completed.returncode:
        detail = (completed.stderr or completed.stdout or "Yosys elaboration failed").strip()
        raise RuntimeError(detail[-6000:])
    try:
        netlist = json.loads(output.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Yosys did not produce a valid hierarchy JSON: {exc}") from exc
    graph = build_rtl_hierarchy(netlist, top=top)
    graph["tool"] = "Yosys"
    graph["frontend"] = "yosys-slang/read_slang" if frontend == "slang" else "Yosys read_verilog -sv"
    graph["sv_standard"] = sv_standard if frontend == "slang" else None
    graph["source_files"] = [str(path.relative_to(root)) for path in resolved]
    graph["yosys_log"] = (completed.stdout or "")[-4000:]
    return graph



def load_riscv_core_sources(project_root: str | Path,
                           python: str | None = None) -> list[str]:
    """Read the RISC-V project's authoritative RTL list from sim/run.py."""
    import ast
    root = Path(project_root).resolve()
    runner = root / "sim" / "run.py"
    if not runner.is_file():
        raise FileNotFoundError(f"RISC-V simulation source list not found: {runner}")
    try:
        syntax = ast.parse(runner.read_text(encoding="utf-8"), filename=str(runner))
    except (OSError, SyntaxError) as exc:
        raise RuntimeError(f"Cannot parse RISC-V sim/run.py source list: {exc}") from exc
    raw_sources = None
    for statement in syntax.body:
        if isinstance(statement, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "RTL_SRCS"
                for target in statement.targets):
            try:
                raw_sources = ast.literal_eval(statement.value)
            except (ValueError, TypeError) as exc:
                raise RuntimeError("RTL_SRCS in sim/run.py must be a literal list") from exc
            break
    if not isinstance(raw_sources, list) or not raw_sources:
        raise RuntimeError("Could not find a non-empty literal RTL_SRCS list in sim/run.py")
    sources = []
    for item in raw_sources:
        value = str(item).strip()
        if not value.startswith("rtl/"):
            value = "rtl/" + value
        sources.append(value)
    if any(not item.endswith((".sv", ".v")) for item in sources):
        raise RuntimeError("sim/run.py RTL_SRCS contains a non-Verilog source entry")
    if not sources:
        raise RuntimeError("RISC-V sim/run.py returned an empty RTL source list")
    missing = [source for source in sources if not (root / source).is_file()]
    if missing:
        raise FileNotFoundError("RISC-V RTL list contains missing files: " +
                                ", ".join(missing[:20]))
    if "rtl/rv64_pkg.sv" not in sources or "rtl/riscv_core_top.sv" not in sources:
        raise RuntimeError("RISC-V RTL list must include rv64_pkg.sv and riscv_core_top.sv")
    if sources.index("rtl/rv64_pkg.sv") > sources.index("rtl/riscv_core_top.sv"):
        raise RuntimeError("RISC-V package must precede dependent RTL files")
    return sources



def _slang_type_width(type_name: str, member: dict[str, Any] | None = None) -> int | None:
    """Best-effort packed width from Slang's elaborated type display."""
    for key in ("bitWidth", "width"):
        value = (member or {}).get(key)
        if isinstance(value, int) and value > 0:
            return value
    ranges = re.findall(r"\[(\d+)\s*:\s*(\d+)\]", type_name or "")
    if not ranges:
        return 1 if type_name else None
    width = 1
    for left, right in ranges:
        width *= abs(int(left) - int(right)) + 1
    return width


def _slang_source_info(node: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("source", "sourceLocation", "location", "declaredAt"):
        value = node.get(key)
        if isinstance(value, dict):
            file_name = value.get("file") or value.get("path") or value.get("filename")
            line = value.get("line") or value.get("lineNumber")
            if file_name:
                return {"file": str(file_name), "line": int(line or 1), "raw": value}
        elif isinstance(value, str):
            match = re.match(r"(.+?):(\d+)(?::(\d+))?", value)
            if match:
                return {"file": match.group(1), "line": int(match.group(2)),
                        "column": int(match.group(3) or 1), "raw": value}
    return None


def _slang_named_symbols(expression: Any) -> list[tuple[str, str]]:
    """Return (symbol address, source-level name) pairs from a Slang expression."""
    found: list[tuple[str, str]] = []
    def visit(value: Any) -> None:
        if isinstance(value, dict):
            symbol = value.get("symbol")
            if isinstance(symbol, str):
                match = re.match(r"^(\d+)\s+(.+)$", symbol)
                if match:
                    found.append((match.group(1), match.group(2)))
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(expression)
    # Preserve order while removing duplicate references.
    return list(dict.fromkeys(found))


def build_hierarchy_from_slang_ast(ast_document: dict[str, Any], *,
                                   top: str, max_instances: int = MAX_INSTANCES) -> dict[str, Any]:
    """Build instance hierarchy and actual port-expression connections from Slang AST JSON."""
    design = ast_document.get("design") or {}
    top_instance = next((item for item in design.get("members", [])
                         if item.get("kind") == "Instance" and item.get("name") == top), None)
    if top_instance is None:
        available = [item.get("name") for item in design.get("members", [])
                     if item.get("kind") == "Instance"]
        raise ValueError(f"Top instance {top!r} not found in Slang AST; available: {available}")

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    truncated = False

    def walk(instance: dict[str, Any], instance_path: str,
             parent_body: dict[str, Any] | None = None) -> None:
        nonlocal truncated
        if len(nodes) >= max_instances:
            truncated = True
            return
        raw_body = instance.get("body")
        body = raw_body if isinstance(raw_body, dict) else {}
        module_name = (body.get("name") or
                       (raw_body if isinstance(raw_body, str) else None) or
                       instance.get("module") or instance.get("name", ""))
        members = body.get("members") or []
        port_members = [member for member in members if member.get("kind") == "Port"]
        if not port_members:
            # Slang can serialize external / black-box instances without an
            # InstanceBody. Their elaborated connection records still carry
            # the exact formal port name, direction and type.
            port_members = [connection.get("port", {})
                            for connection in instance.get("connections") or []]
        ports = []
        for port in port_members:
            type_name = str(port.get("type", ""))
            ports.append({
                "name": port.get("name", ""),
                "direction": {"In": "input", "Out": "output", "InOut": "inout",
                              "Ref": "ref"}.get(port.get("direction"), "inout"),
                "width": _slang_type_width(type_name, port),
                "type": type_name,
                "source": _slang_source_info(port) or _slang_source_info(body),
            })
        node = {
            "id": instance_path, "module": module_name,
            "source": _slang_source_info(instance) or _slang_source_info(body),
            "ports": ports,
        }
        nodes.append(node)

        if parent_body is not None:
            parent_members = parent_body.get("members") or []
            parent_symbols = {str(member.get("addr")): member.get("name", "")
                              for member in parent_members if member.get("addr") is not None}
            for connection in instance.get("connections") or []:
                port = connection.get("port") or {}
                port_name = port.get("name", "")
                expression = connection.get("expr")
                refs = _slang_named_symbols(expression)
                if refs:
                    for symbol_addr, symbol_name in refs:
                        net_name = parent_symbols.get(symbol_addr) or symbol_name
                        edges.append({
                            "from": instance_path.rsplit(".", 1)[0] + "." + net_name,
                            "to": instance_path + "." + port_name,
                            "instance": instance_path, "port": port_name,
                            "direction": {"In": "input", "Out": "output",
                                          "InOut": "inout", "Ref": "ref"}.get(
                                              port.get("direction"), "inout"),
                            "width": _slang_type_width(str(port.get("type", "")), port),
                            "expression_kind": (expression or {}).get("kind"),
                            "parent_symbol": net_name, "parent_symbol_addr": symbol_addr,
                            "source": _slang_source_info(port),
                        })
                else:
                    edges.append({
                        "from": instance_path.rsplit(".", 1)[0] + ".<expression>",
                        "to": instance_path + "." + port_name,
                        "instance": instance_path, "port": port_name,
                        "direction": {"In": "input", "Out": "output",
                                      "InOut": "inout", "Ref": "ref"}.get(
                                          port.get("direction"), "inout"),
                        "width": _slang_type_width(str(port.get("type", "")), port),
                        "expression_kind": (expression or {}).get("kind"),
                        "parent_symbol": None, "expression": expression,
                        "source": _slang_source_info(port),
                    })

        for child in members:
            if child.get("kind") != "Instance":
                continue
            child_path = instance_path + "." + child.get("name", "<unnamed>")
            walk(child, child_path, body)
            if truncated:
                return

    walk(top_instance, top)
    return {
        "top": top, "nodes": nodes, "edges": edges,
        "instance_count": len(nodes), "connection_count": len(edges),
        "connection_unit": "port connections",
        "truncated": truncated, "warnings": [],
        "qualification": "Slang elaborated AST hierarchy and port expressions; logical connectivity, not physical layout",
    }


def elaborate_with_slang_ast(project_root: str | Path, sources: list[str | Path], *,
                             top: str, slang: str = "slang",
                             include_dirs: list[str | Path] | None = None,
                             defines: list[str] | None = None,
                             max_loop_analysis_steps: int = 0,
                             timeout_seconds: int = 300) -> dict[str, Any]:
    """Run standalone Slang full-SV elaboration and export its elaborated AST JSON.

    Driver-loop analysis is disabled by default because hierarchy extraction does
    not require procedural driver unrolling; this avoids synthesis-style unroll
    limits on legal dynamic loops in behavioral functions.
    """
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", top):
        raise ValueError("Top module must be a simple Verilog/SystemVerilog identifier")
    executable = shutil.which(slang)
    if not executable:
        raise RuntimeError("Slang executable not found; install Slang or OSS CAD Suite")
    root = Path(project_root).resolve()
    if not sources:
        raise ValueError("Select at least one SystemVerilog/Verilog source file")
    resolved = []
    for source in sources:
        path = (root / source).resolve() if not Path(source).is_absolute() else Path(source).resolve()
        if root not in path.parents and path != root:
            raise ValueError(f"Source escapes project root: {source}")
        if not path.is_file() or path.suffix.lower() not in {".sv", ".v"}:
            raise ValueError(f"Not a readable Verilog/SystemVerilog source: {source}")
        resolved.append(path)
    incdirs = []
    for directory in include_dirs or []:
        path = (root / directory).resolve() if not Path(directory).is_absolute() else Path(directory).resolve()
        if root not in path.parents and path != root:
            raise ValueError(f"Include directory escapes project root: {directory}")
        if not path.is_dir():
            raise ValueError(f"Include directory does not exist: {directory}")
        incdirs.append(path)
    command = [executable, "--ast-json", str(root / ".wengold" / "slang_ast.json"),
               "--ast-json-source-info", "--max-loop-analysis-steps",
               str(max_loop_analysis_steps)]
    for directory in incdirs:
        command.extend(["-I", str(directory)])
    for define in defines or []:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:=[^\s]+)?", define):
            raise ValueError(f"Invalid preprocessor define: {define}")
        command.append("-D" + define)
    command.extend(str(path) for path in resolved)
    output = root / ".wengold" / "slang_ast.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(command, cwd=root, capture_output=True, text=True,
                               timeout=timeout_seconds, check=False)
    if completed.returncode:
        detail = (completed.stderr or completed.stdout or "Slang elaboration failed").strip()
        raise RuntimeError(detail[-8000:])
    try:
        ast_document = json.loads(output.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Slang did not produce valid AST JSON: {exc}") from exc
    graph = build_hierarchy_from_slang_ast(ast_document, top=top)
    graph["tool"] = "Slang"
    graph["frontend"] = "Slang CLI elaborated AST JSON"
    graph["source_files"] = [str(path.relative_to(root)) for path in resolved]
    graph["diagnostics"] = (completed.stderr or completed.stdout or "")[-8000:]
    return graph


def crossprobe_hierarchy_to_vcd(graph: dict[str, Any], wave: dict[str, Any], *,
                                vcd_root: str, dut_instance: str = "u_core") -> dict[str, Any]:
    """Map elaborated DUT ports to exact VCD hierarchical names.

    Example: graph top riscv_core_top + instance u_fetch + port req_valid maps
    to tb_core_top.u_core.u_fetch.req_valid when vcd_root=tb_core_top.
    Names are matched exactly; no fuzzy signal-name guesses are used.
    """
    root = vcd_root.strip(".")
    dut = dut_instance.strip(".")
    if not root or not dut:
        raise ValueError("Both VCD root and DUT instance prefix are required")
    available = {item.get("name") for item in wave.get("signals", [])}
    top = graph.get("top", "")
    matches = []
    direct_matches = []
    parent_alias_matches = []
    missing = []
    # Slang describes a formal child port, while some simulators emit only the
    # connected parent net in VCD (especially for aliased input/output ports).
    # Permit that fallback only when the elaborated AST gives a concrete parent
    # symbol and that exact hierarchical parent path exists in the VCD.
    edges_by_port: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for edge in graph.get("edges", []):
        edges_by_port.setdefault((edge.get("instance", ""), edge.get("port", "")), []).append(edge)

    def vcd_path_for_hierarchy(hierarchy_path: str) -> str | None:
        if hierarchy_path == top:
            relative_path = ""
        elif hierarchy_path.startswith(top + "."):
            relative_path = hierarchy_path[len(top) + 1:]
        else:
            return None
        return ".".join(part for part in (root, dut, relative_path) if part)

    for node in graph.get("nodes", []):
        instance = node.get("id", "")
        for port in node.get("ports", []):
            path = vcd_path_for_hierarchy(instance)
            if path is None:
                continue
            path += "." + port["name"]
            record = {"instance": instance, "module": node.get("module"),
                      "port": port["name"], "direction": port.get("direction"),
                      "width": port.get("width"), "vcd_path": path}
            if path in available:
                record["match_kind"] = "direct_port"
                direct_matches.append(record)
                matches.append(record)
                continue

            alias_found = False
            for edge in edges_by_port.get((instance, port["name"]), []):
                parent_symbol = edge.get("parent_symbol")
                parent_hierarchy = edge.get("from")
                if not parent_symbol or not parent_hierarchy:
                    continue
                alias_path = vcd_path_for_hierarchy(parent_hierarchy)
                if alias_path and alias_path in available:
                    alias_record = dict(record)
                    alias_record.update({
                        "match_kind": "exact_parent_net_alias",
                        "matched_vcd_path": alias_path,
                        "parent_symbol": parent_symbol,
                    })
                    parent_alias_matches.append(alias_record)
                    matches.append(alias_record)
                    alias_found = True
                    break
            if not alias_found:
                missing.append(record)

    return {
        "vcd_root": root, "dut_instance": dut,
        "matched_ports": len(matches), "direct_matches": len(direct_matches),
        "parent_net_alias_matches": len(parent_alias_matches),
        "unmatched_ports": len(missing),
        "total_ports": len(matches) + len(missing),
        "matches": matches, "direct_match_records": direct_matches,
        "parent_net_alias_records": parent_alias_matches, "unmatched": missing,
        "status": "matched" if matches else "no_exact_matches",
        "qualification": ("Direct hierarchical port matches plus exact parent-net aliases "
                          "from Slang elaborated connections; no fuzzy name matching"),
    }
