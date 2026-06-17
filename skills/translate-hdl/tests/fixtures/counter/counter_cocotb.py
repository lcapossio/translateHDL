# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Leonardo Capossio - bard0 design
# Author: Leonardo Capossio - bard0 design - hello@bard0.com
"""cocotb twin of counter_trace_tb.{v,vhd}.

One Python testbench drives BOTH the VHDL and Verilog counter through
cocotb (ghdl + icarus respectively). Emitting the same TRACE lines from
the same Python code on both sides removes the testbench-isomorphism risk
the native pair carries.

Matches the native pair's behavior:
  * 10 ns clock period (5 ns half-period).
  * Sample 1 ns AFTER each rising edge (same #1 / wait for 1 ns the
    native benches use).
  * Same stimulus pattern: reset cycle, 20 enabled, 3 disabled, 10 enabled,
    1 reset-dominates-enable, 5 enabled-after-reset.
  * Prints 1 "TRACE reset count=N" line and 39 "TRACE rst=R en=E count=N"
    lines -> 40 marker lines, byte-identical to the native pair output.

Use ``print()`` not ``dut._log.info()`` so the lines pass through the
simulator stdout unprefixed and the L3a comparator's
``startswith("TRACE ")`` filter matches.
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer


def _i(sig):
    """Coerce a cocotb signal value (LogicArray / BinaryValue) to a plain int."""
    return int(sig.value)


@cocotb.test()
async def counter_trace_test(dut):
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())

    dut.rst.value = 1
    dut.en.value = 0
    await RisingEdge(dut.clk)
    await Timer(1, units="ns")
    print(f"TRACE reset count={_i(dut.count)}")

    async def step():
        await RisingEdge(dut.clk)
        await Timer(1, units="ns")
        print(f"TRACE rst={_i(dut.rst)} en={_i(dut.en)} count={_i(dut.count)}")

    dut.rst.value = 0
    dut.en.value = 1
    for _ in range(20):
        await step()

    dut.en.value = 0
    for _ in range(3):
        await step()

    dut.en.value = 1
    for _ in range(10):
        await step()

    dut.rst.value = 1
    dut.en.value = 1
    await step()

    dut.rst.value = 0
    for _ in range(5):
        await step()

    print("PASS: counter trace bench")
