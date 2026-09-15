# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Leonardo Capossio - bard0 design
# Author: Leonardo Capossio - bard0 design - hello@bard0.com
"""Shared helpers for the translateHDL parity ladder.

Conventions
-----------
Every layer script is both importable and runnable as ``python scripts/<x>.py
<manifest.yml>``. Each returns a :class:`LayerResult`; as a CLI it maps the
status to a process exit code:

* ``PASS``    -> 0   (verified)
* ``FAIL``    -> 1   (a real divergence was found)
* ``SKIP``    -> 77  (a required external tool is not installed)
* ``BOUNDED`` -> 77  (no divergence up to a depth; NOT a full proof)
* ``N/A``     -> 0   (this layer had nothing to check for this manifest)

The SKIP code (77, the autotools convention) lets the orchestrator and CI tell
"tool missing" apart from "designs differ" so a missing simulator never
masquerades as a passing proof.

``N/A`` exists so an OPTIONAL layer that was never asked to do anything cannot
be read as evidence. A layer returning PASS asserts "I checked, and it holds";
a layer with nothing configured must say N/A instead, or an unconfigured
optional layer would silently contribute a passing verdict.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# Tool binaries can be overridden by environment variable, so installs with
# non-standard names work without code changes (e.g. YoWASP: YOSYS=yowasp-yosys,
# GHDL=yowasp-ghdl; or a pinned path: GHDL=/path/to/ghdl).
_TOOL_ENV = {
    "yosys": "YOSYS", "ghdl": "GHDL", "iverilog": "IVERILOG",
    "vvp": "VVP", "eqy": "EQY",
}


def tool(name: str) -> str:
    return os.environ.get(_TOOL_ENV.get(name, ""), "") or name

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"
BOUNDED = "BOUNDED"   # equivalent up to a bounded depth, but not fully proven
N_A = "N/A"           # layer not configured for this manifest; NOT evidence

# BOUNDED and SKIP both mean "not a full proof, but no divergence found" -> 77.
# N_A is 0: nothing was asked of the layer, so it is not a failure - but the
# orchestrator must not fold it into a PASS verdict either (see parity.py).
EXIT = {PASS: 0, FAIL: 1, SKIP: 77, BOUNDED: 77, N_A: 0}


class ToolMissing(Exception):
    """Raised when a required external tool is absent from PATH."""

    def __init__(self, tools: list[str]):
        self.tools = tools
        super().__init__("missing required tool(s): " + ", ".join(tools))


@dataclass
class LayerResult:
    layer: str
    status: str
    detail: str = ""
    items: list[tuple[str, str, str]] = field(default_factory=list)

    def add(self, name: str, status: str, detail: str = "") -> None:
        self.items.append((name, status, detail))

    @property
    def exit_code(self) -> int:
        return EXIT[self.status]

    def rollup(self) -> str:
        """Derive overall status from sub-items (FAIL > BOUNDED > SKIP > PASS).

        N_A items are neutral: they carry no evidence either way, so they are
        ignored unless EVERY item is N_A (then the layer as a whole did
        nothing and must say so rather than claim a pass).
        """
        if not self.items:
            return self.status
        statuses = {status for _, status, _ in self.items}
        if statuses == {N_A}:
            return N_A
        statuses.discard(N_A)
        if FAIL in statuses:
            return FAIL
        if BOUNDED in statuses:
            # a bounded-only proof anywhere means the layer is not a full proof
            return BOUNDED
        if SKIP in statuses:
            # any skip -> partial; never mistaken for a full proof.
            return SKIP
        return PASS


def have(name: str) -> bool:
    return shutil.which(tool(name)) is not None


def require(*tools: str) -> None:
    missing = [t for t in tools if not have(t)]
    if missing:
        raise ToolMissing(missing)


def run(cmd: list[str], cwd: Path, *, capture: bool = False,
        input_text: str | None = None, check: bool = True) -> subprocess.CompletedProcess:
    print("+ " + " ".join(str(c) for c in cmd), flush=True)
    result = subprocess.run(
        [str(c) for c in cmd],
        cwd=str(cwd),
        text=True,
        input=input_text,
        capture_output=capture,
        check=False,          # this wrapper raises below, with output attached
    )
    if check and result.returncode != 0:
        if capture:
            if result.stdout:
                print(result.stdout, end="")
            if result.stderr:
                print(result.stderr, end="", file=sys.stderr)
        raise subprocess.CalledProcessError(result.returncode, cmd, result.stdout, result.stderr)
    return result


def run_capture(cmd: list[str], cwd: Path, *, input_text: str | None = None) -> str:
    print("+ " + " ".join(str(c) for c in cmd), flush=True)
    try:
        return subprocess.check_output(
            [str(c) for c in cmd],
            cwd=str(cwd),
            text=True,
            input=input_text,
            stderr=subprocess.STDOUT,
        )
    except subprocess.CalledProcessError as err:
        if err.output:
            print(err.output, end="")
        raise


def run_output(cmd: list[str], cwd: Path, *, input_text: str | None = None,
               timeout: float | None = None) -> tuple[int, str]:
    """Run a command, returning (returncode, combined stdout+stderr) without raising.

    Use when correctness must be decided by parsing the tool's *output* rather
    than its exit code — some tool builds (notably yowasp-yosys) do not reliably
    propagate a non-zero exit on an internal assertion failure.

    ``timeout`` (seconds) guards solvers that can run unboundedly — temporal
    induction raises the induction length until it closes, which for a true but
    non-k-inductive property never happens. The caller gets
    ``subprocess.TimeoutExpired`` and must map it to a NON-PASS status: an
    unfinished proof is not a proof.
    """
    print("+ " + " ".join(str(c) for c in cmd), flush=True)
    p = subprocess.run(
        [str(c) for c in cmd],
        cwd=str(cwd),
        text=True,
        input=input_text,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,          # the whole point: the CALLER judges by output
        timeout=timeout,      # None = wait forever (the default everywhere else)
    )
    return p.returncode, (p.stdout or "")


def load_manifest(path: str | Path) -> dict:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        # A malformed manifest is bad user input, not a caller type error, so
        # ValueError (what the rest of the ladder catches) stands; TRY004 muted.
        raise ValueError(f"{path}: manifest must be a YAML mapping")  # noqa: TRY004
    return data


def manifest_root(path: str | Path) -> Path:
    """Paths inside a manifest are resolved relative to the manifest's dir."""
    return Path(path).resolve().parent


def resolve_sources(root: Path, sources: list[str]) -> list[str]:
    out: list[str] = []
    for src in sources:
        p = (root / src)
        if not p.exists():
            raise FileNotFoundError(f"source not found: {p}")
        out.append(str(p))
    return out


def cli_main(layer_fn) -> None:
    """Run a layer function as a CLI: ``layer_fn(manifest_path) -> LayerResult``."""
    if len(sys.argv) != 2:
        prog = Path(sys.argv[0]).name
        print(f"usage: python scripts/{prog} <manifest.yml>", file=sys.stderr)
        raise SystemExit(2)
    try:
        result = layer_fn(sys.argv[1])
    except ToolMissing as exc:
        print(f"\nSKIP: {exc}", file=sys.stderr)
        raise SystemExit(EXIT[SKIP])
    status = result.rollup()
    print(f"\n{status}: {result.layer} - {result.detail}".rstrip(" -"))
    raise SystemExit(EXIT[status])
