# Examples

## spwstream_trace

Reproduces [spacewire_light](https://github.com/lcapossio)'s VHDL↔Verilog
`streamtest` parity (deterministic trace + normalized waveform) through the
generic translateHDL harness.

**Prerequisite:** `spacewire_light` checked out as a sibling of `translateHDL`:

```
<parent>/
  translateHDL/
  spacewire_light/
```

**Run** (needs `ghdl` + `iverilog`):

```sh
cd examples/spwstream_trace
python ../../scripts/parity.py parity.yml
```

Expected: L3a (trace) and L3b (waveform) PASS; L0 defers (record vs flattened
ports, no map); L1/L2/L4 SKIP unless you add Yosys and an interface wrapper.

This shows the simulation layers working on a real core. To add the formal proof
for the record-port modules, supply a per-module interface wrapper as described
in [../rules/interface_contract.md](../rules/interface_contract.md).
