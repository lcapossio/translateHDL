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
* ``yosys_read_formal`` — same, but preserving assertions and assumptions as
                       ``$assert``/``$assume`` cells (Layer 2b: property
                       checking). Distinct from ``yosys_read`` because the plain
                       read path deliberately *drops* properties. Each language
                       preserves only the subset its reader supports, so the
                       caller must verify the cell count rather than assume
                       every written property survived.

VHDL is brought into Yosys by emitting a Verilog netlist with
``ghdl --synth --out=verilog`` (the approach proven in spacewire_light's
synth_resource_compare.py); Verilog is read natively.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from _common import require, run, run_capture, tool


@dataclass
class SimResult:
    stdout: str


def yosys_path(path: str | Path) -> str:
    """Render a filesystem path for a Yosys command line.

    as_posix: Yosys reads a backslash as an escape, so a Windows path must be
    forward-slashed. Quoted when it contains whitespace, which Yosys' command
    parser would otherwise split into two filenames.
    """
    text = Path(path).as_posix()
    return f'"{text}"' if any(c.isspace() for c in text) else text


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

    def yosys_read_formal(self, root: Path, top: str, sources: list[str], *,
                          props: list[str] | None = None,
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
        # The bench must honour +WAVE=<path>. Give the receiving reg room
        # for a real path - at least `reg [4095:0]` (512 chars); a
        # `reg [1023:0]` holds 128 and $value$plusargs front-truncates
        # silently past that. Worked bench:
        # tests/fixtures/counter/counter_trace_tb.v
        return self.simulate(root, top, sources, plusargs=[f"+WAVE={vcd}"])

    def lint(self, root, sources, *, std="2001") -> None:
        require("iverilog")
        run([tool("iverilog"), "-g2001", "-Wall", "-tnull", *sources], root)

    def yosys_read(self, root, top, sources, *, params=None, std="2001", workdir=None) -> list[str]:
        require("yosys")
        cmds = ["read_verilog " + " ".join(yosys_path(s) for s in sources)]
        chparam = ""
        for key, val in (params or {}).items():
            chparam += f" -chparam {key} {int(val)}"
        cmds.append(f"hierarchy -check -top {top}{chparam}")
        return cmds

    def yosys_read_formal(self, root, top, sources, *, props=None, params=None,
                          std="2001", workdir=None) -> list[str]:
        # -formal keeps assert/assume as $assert/$assume cells instead of
        # discarding them; -sv accepts the SystemVerilog assertion forms native
        # Yosys supports - immediate `assert`, `$past` in clocked blocks - NOT
        # full concurrent SVA or `bind`, which need the Verific frontend. A
        # Verilog-2001 RTL file stays legal under the SV reader, so this is safe
        # to use for both the RTL and the property harness.
        require("yosys")
        files = " ".join(yosys_path(s) for s in [*sources, *(props or [])])
        chparam = "".join(f" -chparam {k} {int(v)}" for k, v in (params or {}).items())
        return [f"read_verilog -sv -formal {files}", f"hierarchy -check -top {top}{chparam}"]


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

    def yosys_read_formal(self, root, top, sources, *, props=None, params=None,
                          std="08", workdir=None) -> list[str]:
        # PSL cannot survive the `ghdl --synth --out=verilog` netlist bridge used
        # by yosys_read, so property checking goes through the ghdl-yosys-plugin
        # instead: yosys' `ghdl` command elaborates in-process with -fpsl, keeping
        # PSL asserts/assumes as $assert/$assume cells. GHDL supports a SUBSET of
        # PSL, and its synthesis path is upstream-documented as experimental -
        # which is exactly why properties.py verifies the resulting cell count
        # instead of trusting that everything written was read.
        # Availability of that plugin is the caller's check (see properties.py).
        require("ghdl", "yosys")
        files = " ".join(yosys_path(s) for s in [*sources, *(props or [])])
        gen = "".join(f" -g{k}={int(v)}" for k, v in (params or {}).items())
        return [f"ghdl --std={std} -fsynopsys -fpsl {files} -e{gen} {top}",
                f"hierarchy -check -top {top}"]


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
