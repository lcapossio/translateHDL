# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Leonardo Capossio - bard0 design
# Author: Leonardo Capossio - bard0 design - hello@bard0.com
"""Per-language toolchain registry.

Adding a new source/target language means adding one :class:`Language`
implementation here and a ``rules/<from>_to_<to>.md`` guide — the parity
ladder scripts stay language-neutral by going through this interface.

Each Language knows how to:

* ``simulate``       — build+run a testbench, return its stdout (Layer 3 trace)
* ``simulate_vcd``   — same, but also emit a VCD at a chosen path (Layer 3 wave)
* ``lint``           — analyze/elaborate the sources clean (Layer 1)
* ``yosys_read``     — yield Yosys commands that leave ``top`` loaded as the
                       current/whole design, applying integer parameters
                       (Layers 2 & 4: formal SEC and synth-stat)

VHDL is brought into Yosys by emitting a Verilog netlist with
``ghdl --synth --out=verilog`` (the approach proven in spacewire_light's
synth_resource_compare.py); Verilog is read natively.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from _common import require, run, run_capture, tool


@dataclass
class SimResult:
    stdout: str


class Language:
    name: str = ""

    def simulate(self, root: Path, top: str, sources: list[str], *,
                 std: str = "08", plusargs: list[str] | None = None) -> str:
        raise NotImplementedError

    def simulate_vcd(self, root: Path, top: str, sources: list[str], vcd: Path, *,
                     std: str = "08") -> str:
        raise NotImplementedError

    def lint(self, root: Path, sources: list[str], *, std: str = "08") -> None:
        raise NotImplementedError

    def yosys_read(self, root: Path, top: str, sources: list[str], *,
                   params: dict[str, int] | None = None, std: str = "08",
                   workdir: Path | None = None) -> list[str]:
        raise NotImplementedError


class Verilog(Language):
    name = "verilog"

    def _compile(self, root: Path, top: str, sources: list[str], out: Path) -> None:
        require("iverilog")
        run([tool("iverilog"), "-g2001", "-s", top, "-o", str(out), *sources], root)

    def simulate(self, root, top, sources, *, std="2001", plusargs=None) -> str:
        require("iverilog", "vvp")
        out = root / f".{top}.vvp"
        self._compile(root, top, sources, out)
        try:
            return run_capture([tool("vvp"), str(out), *(plusargs or [])], root)
        finally:
            out.unlink(missing_ok=True)

    def simulate_vcd(self, root, top, sources, vcd, *, std="2001") -> str:
        # bench is expected to honour +WAVE=<path> (see templates/).
        return self.simulate(root, top, sources, plusargs=[f"+WAVE={vcd}"])

    def lint(self, root, sources, *, std="2001") -> None:
        require("iverilog")
        run([tool("iverilog"), "-g2001", "-Wall", "-tnull", *sources], root)

    def yosys_read(self, root, top, sources, *, params=None, std="2001", workdir=None) -> list[str]:
        require("yosys")
        cmds = ["read_verilog " + " ".join(sources)]
        chparam = ""
        for key, val in (params or {}).items():
            chparam += f" -chparam {key} {int(val)}"
        cmds.append(f"hierarchy -check -top {top}{chparam}")
        return cmds


class Vhdl(Language):
    name = "vhdl"

    def _analyze(self, root: Path, sources: list[str], std: str) -> None:
        require("ghdl")
        run([tool("ghdl"), "--remove"], root, check=False)
        for cf in root.glob("work-obj*.cf"):
            cf.unlink()
        run([tool("ghdl"), "-a", f"--std={std}", "-fsynopsys", *sources], root)

    def simulate(self, root, top, sources, *, std="08", plusargs=None) -> str:
        require("ghdl")
        self._analyze(root, sources, std)
        run([tool("ghdl"), "-e", f"--std={std}", "-fsynopsys", top], root)
        try:
            return run_capture(
                [tool("ghdl"), "-r", f"--std={std}", "-fsynopsys", top, "--assert-level=error"],
                root,
            )
        finally:
            for cf in root.glob("work-obj*.cf"):
                cf.unlink()

    def simulate_vcd(self, root, top, sources, vcd, *, std="08") -> str:
        require("ghdl")
        self._analyze(root, sources, std)
        run([tool("ghdl"), "-e", f"--std={std}", "-fsynopsys", top], root)
        try:
            return run_capture(
                [tool("ghdl"), "-r", f"--std={std}", "-fsynopsys", top,
                 "--assert-level=error", f"--vcd={vcd}"],
                root,
            )
        finally:
            for cf in root.glob("work-obj*.cf"):
                cf.unlink()

    def lint(self, root, sources, *, std="08") -> None:
        require("ghdl")
        self._analyze(root, sources, std)

    def netlist(self, root: Path, top: str, sources: list[str], out: Path, *,
                std: str = "08", params: dict[str, int] | None = None) -> None:
        """Emit a Verilog netlist for `top` via ghdl --synth (VHDL->Yosys bridge)."""
        require("ghdl")
        self._analyze(root, sources, std)
        gen = []
        for key, val in (params or {}).items():
            gen += ["-g" + f"{key}={int(val)}"]
        with out.open("w", encoding="utf-8") as handle:
            print(f"+ ghdl --synth --out=verilog {top} > {out}", flush=True)
            import subprocess
            subprocess.run(
                [tool("ghdl"), "--synth", f"--std={std}", "-fsynopsys", "--out=verilog", *gen, top],
                cwd=str(root), stdout=handle, check=True, text=True,
            )
        for cf in root.glob("work-obj*.cf"):
            cf.unlink()

    def yosys_read(self, root, top, sources, *, params=None, std="08", workdir=None) -> list[str]:
        require("ghdl", "yosys")
        workdir = workdir or root
        net = workdir / f"_vhdl_netlist_{top}.v"
        self.netlist(root, top, sources, net, std=std, params=params)
        return [f"read_verilog {net.as_posix()}", f"hierarchy -check -top {top}"]


REGISTRY: dict[str, Language] = {
    "verilog": Verilog(),
    "vhdl": Vhdl(),
}


def get(language: str) -> Language:
    try:
        return REGISTRY[language.lower()]
    except KeyError:
        raise SystemExit(f"ERROR: unsupported language '{language}'. "
                         f"Known: {', '.join(sorted(REGISTRY))}")
