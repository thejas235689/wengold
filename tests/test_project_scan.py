"""Real project discovery and Qt file-loader behavior for Silicon Studio."""
from pathlib import Path

from wengold.project_scan import discover, category
from wengold.desktop import build_state
from wengold.studio_workspace import source, save_source


def test_project_folders_separate_design_uvm_automation(tmp_path):
    items = {
        "rtl/cpu.sv": "module cpu; endmodule\n",
        "dv/uvm/agent.sv": "class agent; endclass\n",
        "tb/tb_top.sv": "module tb_top; endmodule\n",
        "scripts/run.py": "print(1)\n",
        "scripts/run.tcl": "puts yes\n",
        "sim/compile.f": "rtl/cpu.sv\n",
        "verification/sequence.pss": "component c {};\n",
    }
    for path, body in items.items():
        absolute = tmp_path / path
        absolute.parent.mkdir(parents=True, exist_ok=True)
        absolute.write_text(body)
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "ignore.sv").write_text("module ignored; endmodule")
    found = discover(tmp_path)
    assert "rtl/cpu.sv" in found["design"]
    assert "dv/uvm/agent.sv" in found["verification"]
    assert "tb/tb_top.sv" in found["verification"]
    assert "verification/sequence.pss" in found["verification"]
    assert "scripts/run.py" in found["automation"]
    assert "scripts/run.tcl" in found["automation"]
    assert "sim/compile.f" in found["filelists"]
    assert "ignore.sv" not in str(found)
    state = build_state(str(tmp_path))
    assert "scripts/run.py" in state["file_paths"]
    assert "dv/uvm/agent.sv" in state["file_paths"]
    assert "rtl/cpu.sv" in state["file_paths"]


def test_project_automation_is_readable_and_guarded_on_save(tmp_path):
    script = tmp_path / "tools" / "regression.py"
    script.parent.mkdir()
    script.write_text("print(1)\n")
    data = source(tmp_path, "tools/regression.py")
    assert data["content"] == "print(1)\n"
    changed = save_source(tmp_path, "tools/regression.py", "print(2)\n", data["sha256"])
    assert changed["changed"]
    assert script.read_text() == "print(2)\n"
    from wengold.ide_server import Refused
    import pytest
    with pytest.raises(Refused):
        source(tmp_path, "../escape.sh")
    with pytest.raises(Refused):
        save_source(tmp_path, "tools/regression.py", "print(3)", data["sha256"])


def test_scan_detects_external_updates(tmp_path):
    rtl = tmp_path / "a.sv"
    rtl.write_text("module a; endmodule")
    first = discover(tmp_path)["signature"]
    rtl.write_text("module b; endmodule // changed")
    assert first != discover(tmp_path)["signature"]
    (tmp_path / "tb").mkdir()
    (tmp_path / "tb" / "b_tb.sv").write_text("module b_tb; endmodule")
    assert discover(tmp_path)["counts"]["verification"] == 1


def test_hdl_indexer_skips_generated_build_and_venv(tmp_path):
    from wengold.cli import _collect
    for folder in ("build", ".venv", ".git", "rtl"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "core.sv").write_text("module core; endmodule")
    files = _collect(str(tmp_path))
    assert list(files) == ["rtl/core.sv"]
