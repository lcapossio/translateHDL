# VHDL → Verilog-2001 translation rules

The prime directive: **translate faithfully and preserve state.** A faithful,
register-for-register translation is what lets Layer 2 (formal SEC) close
automatically. Clever rewrites that change the state encoding turn a push-button
proof into an unprovable mess. When in doubt, mirror the original structure.

## 1. The two-process pattern (the backbone)

Most SpaceWire-Light-style VHDL uses a clocked + combinational two-process FSM
with a record of registers `r`, a variable `v := r`, and `rin <= v`:

```vhdl
signal r, rin : regs_type;
process (r, rst, ...) is
    variable v : regs_type;
begin
    v := r;
    ... -- compute next state into v
    if rst = '1' then v := regs_reset; end if;
    -- drive outputs from r (registered) ...
    rin <= v;
end process;
process (clk) is begin
    if rising_edge(clk) then r <= rin; end if;
end process;
```

Translate it to a Verilog combinational block writing mirror variables `v_*`,
plus a clocked block:

```verilog
reg [W-1:0] state, v_state;          // one pair per register field
always @* begin
    v_state = state;                 // v := r
    ... // compute next state into v_*
    if (rst) begin v_state = RESET; ... end
    // drive outputs from the REGISTERED names (state, ...), mirroring VHDL's r
end
always @(posedge clk) begin
    state <= v_state;                // r <= rin
end
initial begin state = RESET; ... end // mirror the VHDL signal init values
```

Rules:
- One `v_<field>` per record field. Keep field names.
- Outputs that VHDL drives from `r.x` must be driven from the **registered** reg
  `x` in Verilog, *not* `v_x`. (See spwlink.v outputs — they read `state`,
  `tx_credit`, etc., never the `v_` mirrors.) Getting this wrong is the classic
  one-cycle-off bug; formal SEC will catch it, but get it right by construction.
- Reproduce the VHDL signal initializer as a Verilog `initial` block so power-on
  state matches (and so `equiv_induct` starts from the same reset state).

## 2. Records → flattened ports

Verilog-2001 has no record type. Flatten each record port into individual ports
named `<record>_<field>` and keep direction. Document the mapping (see
[interface_contract.md](interface_contract.md)); it also feeds the manifest
`interface.port_map` and any formal wrapper.

```
linki : in spw_link_in_type;   -->   input wire linki_linkstart,
                                      input wire linki_autostart, ...
```

## 3. Types and arithmetic

| VHDL | Verilog-2001 |
| --- | --- |
| `std_logic` / `std_ulogic` | 1-bit `wire`/`reg` |
| `std_logic_vector(N-1 downto 0)` | `[N-1:0]` |
| `unsigned`/`signed` (numeric_std) | plain vectors; use `$signed` only where VHDL was `signed` |
| `to_unsigned(K, n)` | sized literal `n'dK` |
| `x + to_unsigned(8, x'length)` | `x + 6'd8` (match the width!) |
| `bool_to_logic(cond)` | `(cond)` used directly as a 1-bit value |
| enumerated `state_type` | `localparam` one-hot/binary codes; keep the **same** encoding the synthesizer would pick, or set it explicitly on both sides |

Width discipline: VHDL `unsigned` arithmetic wraps at the declared width.
Replicate widths exactly (`reg [5:0] tx_credit;` for a `unsigned(5 downto 0)`),
so wrap/truncation behavior is identical — formal SEC checks this bit-for-bit.

## 4. Generics → parameters

VHDL `generic` integers become Verilog `parameter`s with the same name and
default. **Real-valued generics have no Verilog-2001 equivalent** — precompute
them into integer parameters (spacewire turns `sysfreq`/`txclkfreq` reals into
`RESET_TIME`/`DISCONNECT_TIME`/`DEFAULT_DIVCNT`). Document the precomputation and
choose the parameter sets in the manifest so every used configuration is proven.

## 5. Reset

Match reset *kind* exactly: VHDL synchronous reset (`if rst=… inside rising_edge`
or applied to `v` before `rin<=v`) → Verilog synchronous reset inside
`always @(posedge clk)` (or in the `always @*` writing `v_*`). Async reset
(`if rst then … elsif rising_edge`) → `always @(posedge clk or posedge rst)`.
A sync-vs-async mismatch is a real functional difference and SEC will fail.

## 6. After translating — prove it

1. Add/extend a parity manifest (see [../templates/parity_manifest.yml](../templates/parity_manifest.yml)).
2. `python scripts/parity.py <manifest>.yml --strict` in an env with the full
   toolchain. Layer 2 PASS = formally equivalent. Don't declare done on
   simulation alone.

See also [pitfalls.md](pitfalls.md) for the sharp edges.
