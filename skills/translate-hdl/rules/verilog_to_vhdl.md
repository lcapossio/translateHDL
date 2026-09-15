# Verilog-2001 → VHDL translation rules

Same prime directive as the other direction: **faithful, state-preserving**
translation so formal SEC closes. This guide covers the Verilog→VHDL specifics;
read [vhdl_to_verilog.md](vhdl_to_verilog.md) for the shared two-process model
and [pitfalls.md](pitfalls.md) for the traps.

## 1. Module → entity/architecture

```verilog
module foo #(parameter W = 8) (input wire clk, input wire [W-1:0] d, output reg q);
```
→
```vhdl
entity foo is
    generic ( W : integer := 8 );
    port (
        clk : in  std_logic;
        d   : in  std_logic_vector(W-1 downto 0);
        q   : out std_logic
    );
end entity foo;
architecture rtl of foo is ... begin ... end architecture;
```

Keep port names and order. `output reg` becomes an `out` port driven by a signal
(VHDL can't read an `out` port pre-2008; if the RTL reads its own output, add an
internal signal and assign the port from it).

## 2. Always blocks → processes

| Verilog | VHDL |
| --- | --- |
| `always @(posedge clk)` with `<=` | `process(clk) begin if rising_edge(clk) then … end if; end process;` (use `<=`) |
| `always @(posedge clk or posedge rst)` | `process(clk, rst)` with `if rst='1' … elsif rising_edge(clk)` |
| `always @*` with `=` | `process(<sensitivity>)` with `:=` on variables or `<=` on signals, or concurrent assignments |
| `assign y = expr;` | `y <= expr;` (concurrent) |

Blocking `=` in a combinational block maps to VHDL **variables** (`:=`) inside a
process, or to concurrent signal assignments. Nonblocking `<=` in a clocked block
maps to VHDL signal `<=` inside `rising_edge`. Preserve blocking-vs-nonblocking
semantics exactly — mixing them changes behavior.

## 3. Types

| Verilog | VHDL |
| --- | --- |
| `wire`/`reg` (1-bit) | `std_logic` |
| `[N-1:0]` | `std_logic_vector(N-1 downto 0)` |
| arithmetic `+ - *` on vectors | wrap operands in `unsigned(...)`/`signed(...)` (numeric_std), assign back with `std_logic_vector(...)` |
| `$signed(x)` | `signed(x)` |
| sized literal `6'd8` | `to_unsigned(8, 6)` or `"001000"` |
| concatenation `{a,b}` | `a & b` |
| replication `{N{x}}` | `(others => x)` for full-width, else build explicitly |

VHDL arithmetic needs numeric_std and explicit type wrapping — Verilog's implicit
vector arithmetic must be made explicit, but the **widths and wrap behavior must
stay identical**.

## 4. Parameters → generics

`parameter` → `generic` with matching name/default. Integer params map directly.
Verilog params that were themselves precomputed from reals (translation
artifacts) can stay integer generics; note it in the interface contract.

## 5. X/unknown and initial values

Verilog `initial` register values → VHDL signal initializers (`signal r : … :=
reset_value;`). Verilog `x` has no direct VHDL equal; VHDL uses `'U'`/`'X'`. For
synthesizable RTL this rarely matters, and the parity scripts canonicalize
`U/X/Z/W` together — but don't rely on `x`-propagation differences for behavior.

## 6. After translating — prove it

Build a manifest with `golden.language: verilog`, `candidate.language: vhdl`, and
run `python scripts/parity.py <manifest>.yml --strict`. Layer 2 PASS is the proof.
