# Examples

These run against the **`external/spacewire_light`** submodule. Initialize it once:

```sh
git submodule update --init
```

Each manifest is run with the parity ladder:

```sh
python scripts/parity.py examples/<name>/parity.yml [--strict]
```

The full ladder (esp. Layer 2 formal SEC) needs GHDL + Yosys together — natively
in CI (OSS CAD Suite). On a split local toolchain run the sim layers where the
tools live; see the repo notes.

## syncdff — fully proven
[syncdff/parity.yml](syncdff/parity.yml). Double-FF synchronizer, identical
interface (`clk/rst/di/do`), async reset. **Layer 2 formally proves VHDL ≡
Verilog** (`equiv_status`: equivalence successfully proven). The simplest
real-module win; needs no wrapper.

## spwlink — record ports, bounded-equivalent
[spwlink/parity.yml](spwlink/parity.yml). Exchange-level controller. The VHDL
uses record ports; the Verilog flattens them, so [spwlink_flat.vhd](spwlink/spwlink_flat.vhd)
is a thin VHDL wrapper exposing flat `std_logic` ports with the Verilog names
(see [../rules/interface_contract.md](../rules/interface_contract.md)).

Result: `equiv_make` pairs all ports via the wrapper; k-induction proves **42 of
49** cells. The remaining 7 are FSM/credit-state decodes whose proof is blocked
by the timer-gated FSM + differing enum encoding (VHDL enum vs Verilog binary) —
a known-hard case for plain `equiv_induct`. The `bounded_depth: 40` fallback then
runs a miter SAT check: **no counterexample within 40 cycles of reset**, i.e. the
designs are *bounded-equivalent* and the gap is a proof limitation, not a bug.
Verdict: **BOUNDED**. Full unbounded closure needs a reachability-aware engine
(`formal.engine: eqy`).

## spwstream_trace — simulation parity
[spwstream_trace/parity.yml](spwstream_trace/parity.yml). Reproduces
spacewire_light's deterministic trace + normalized-VCD waveform parity through
the generic harness (needs GHDL + Icarus). Formal SEC for the record-port stream
core would follow the same wrapper recipe as spwlink.
