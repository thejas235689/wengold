"""WENGOLD command line — terminal-native, alongside Git, Tcl and your EDA tools."""
from __future__ import annotations

import typer

app = typer.Typer(add_completion=False, help="WENGOLD — open silicon verification.")


@app.command()
def index(path: str = ".", out: str = ".tof/index.json") -> None:
    """Index a project into a design dependency graph."""
    typer.echo(f"wengold index {path} -> {out}")


@app.command()
def classify(changed: str, revision: str = "HEAD") -> None:
    """Classify prior results against a change set."""
    typer.echo(f"wengold classify --changed {changed} --revision {revision}")


@app.command()
def record(run: str, sim: str = "verilator") -> None:
    """Record a run into the ledger."""
    typer.echo(f"wengold record {run} --sim {sim}")


@app.command()
def demo() -> None:
    """Run the bundled SoC walkthrough."""
    from .demo import main as _main
    _main()


if __name__ == "__main__":
    app()
