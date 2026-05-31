# Translation pitfalls (the bugs that pass eyeballing)

These are the divergences that look right but aren't. Each is something Layer 2
(formal SEC) or Layer 3 (simulation parity) is specifically there to catch — but
avoid them by construction.

## Registered-vs-combinational output (the one-cycle bug)
In the two-process pattern, outputs driven from the VHDL **registered** record
`r.x` must read the Verilog **register** `x`, never the next-state mirror `v_x`.
Reading `v_x` makes the output one cycle early. SEC fails with an unproven output.

## Reset kind / polarity
Sync vs async reset, and active-high vs active-low, are real functional
differences. Match exactly. Also match *what* resets: if VHDL resets only a
subset of registers, reset the same subset.

## Width and wrap
`tx_credit + 8` wraps at 6 bits in VHDL `unsigned(5 downto 0)`. If the Verilog
reg is wider (or `+ 8` is computed at a wider intermediate width), wrap behavior
diverges. Declare identical widths; watch implicit width extension in expressions.

## Blocking vs nonblocking
`=` (blocking) and `<=` (nonblocking) are not interchangeable. A clocked block
must use nonblocking for state; a combinational mirror uses blocking. Swapping
them changes evaluation order and creates races. Mirror the original's intent.

## Sensitivity lists
A combinational `always @*` / VHDL `process(all-inputs)` must be complete.
Missing signals create latches in synthesis and mismatches in simulation. Use
`@*` / VHDL-2008 `process(all)` or list every read signal.

## Signed vs unsigned
VHDL `numeric_std` makes signedness explicit; Verilog defaults to unsigned unless
`signed` is declared / `$signed` is used. Comparisons and shifts differ. Carry the
signedness across faithfully.

## downto vs to, and bit order
VHDL `(N-1 downto 0)` ↔ Verilog `[N-1:0]`. A VHDL `(0 to N-1)` ascending range
reverses bit significance — translate the indexing, don't just copy the numbers.

## Enum encoding
VHDL enumerated state types get an encoding chosen by the synthesizer. If you
hand-pick Verilog `localparam` codes, the encodings may differ — which is fine
for behavior but can slow/break `equiv_induct` (it matches state bit-for-bit).
Either keep encodings identical on both sides, or use the `eqy` engine which can
map differing state via partitioning.

## Integer/real generics
Verilog-2001 has no real parameters. Real VHDL generics must be precomputed to
integers; if you instead drop precision, behavior diverges. Prove every used
parameter set (list them in the manifest `param_sets`).

## `others =>` and replication
`(others => '0')` ↔ `{W{1'b0}}`. For partial assignments these don't translate
1:1 — expand explicitly.

## Multi-driven nets
Verilog silently allows multiple drivers (wired logic / bugs). The Layer 1 Yosys
`check -assert` pass flags these. VHDL resolves multiple drivers via resolution
functions — usually a sign something was mistranslated.

## Don't trust simulation alone
Two designs can match on every testbench you wrote and still differ on an input
you didn't think of. That gap is exactly why Layer 2 formal SEC is the primary
proof here. If SEC can't run for a module, treat parity as *unproven*, not done.
