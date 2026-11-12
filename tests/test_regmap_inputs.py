"""Regression for issue #2: regmap must reject RTL and malformed inputs clearly."""
from argparse import Namespace
from pathlib import Path
from wengold.cli import cmd_regmap


def test_regmap_rejects_systemverilog_without_python_traceback(tmp_path, capsys):
    src = tmp_path / "rv64_csr.sv"
    src.write_text("module rv64_csr; endmodule\n")
    assert cmd_regmap(Namespace(file=str(src))) == 2
    log = capsys.readouterr().out.lower()
    assert "systemrdl" in log and ".sv" in log and "rtl" in log


def test_regmap_invalid_xml_has_human_error(tmp_path, capsys):
    file = tmp_path / "broken.xml"
    file.write_text("<ipxact><")
    assert cmd_regmap(Namespace(file=str(file))) == 2
    assert "input error" in capsys.readouterr().out


def test_regmap_invalid_rdl_has_human_error(tmp_path, capsys):
    file = tmp_path / "broken.rdl"
    file.write_text("module not_rdl; endmodule")
    assert cmd_regmap(Namespace(file=str(file))) == 2
    assert "input error" in capsys.readouterr().out
