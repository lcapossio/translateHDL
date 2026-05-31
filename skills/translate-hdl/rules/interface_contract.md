# Interface contract: record ports across the language gap

VHDL designs often group signals into record ports (e.g. spacewire's
`spw_link_in_type`). Verilog-2001 has no records, so the translated module
exposes **flattened** ports. The "interface contract" is the explicit,
reviewable mapping between the two — it is what makes Layer 0 (interface check)
and Layer 2 (formal SEC, which matches ports by name) work across the gap.

## Naming convention

Flatten `<record>` field `<field>` to a port named `<record>_<field>`, keeping
direction and width:

```
-- VHDL                              // Verilog
linki : in spw_link_in_type;        input  wire       linki_autostart;
  .autostart : std_ulogic             input  wire       linki_linkstart;
  .linkstart : std_ulogic             input  wire [5:0] linki_rxroom;
  .rxroom    : std_logic_vector(5..0) ...
linko : out spw_link_out_type;      output reg        linko_started;
  .started   : std_ulogic             ...
```

## Recording it in the manifest

When golden and candidate use different port spellings (record side vs flattened
side), give the parity scripts the map:

```yaml
interface:
  top: spwlink
  port_map:            # golden_name: candidate_name
    "linki.autostart": linki_autostart
    "linki.linkstart": linki_linkstart
    # ... one line per leaf field ...
```

Layer 0 uses this to check directions/presence. Layer 2 matches ports by name;
when the two sides already agree (the recommended flattened-on-both-sides case,
or std_logic-port VHDL) no map is needed and SEC is push-button.

## Wrapper recipe (proven on spwlink — see `examples/spwlink/spwlink_flat.vhd`)

GHDL flattens a VHDL record port `rec.field` to an escaped Verilog name like
`\rec_rec[field]`, which Yosys `rename` can't easily retarget. Don't fight it —
write a thin **wrapper in the golden side's own language** that exposes the
candidate's flat port names. Concretely, for a VHDL golden with record ports:

1. **Language = the golden side's language.** `_read_cmds` appends the wrapper to
   the golden `sources` and runs the *golden* language handler over all of them,
   so a VHDL golden needs a **VHDL** wrapper (a `.v` wrapper would not compile
   there). The candidate side is untouched.
2. **A new top, not the original name.** The wrapper is a distinct entity (e.g.
   `spwlink_flat`) that instantiates the real one — they can't share a name.
   Point the manifest at it with `formal.modules[].golden_top: spwlink_flat`
   (and `candidate_top:` if the candidate's top differs); list the file in
   `formal.modules[].wrapper`.
3. **Flat ports named exactly like the candidate.** Declare `std_logic` /
   `std_logic_vector` ports `linki_autostart`, `linko_started`, … matching the
   Verilog one-for-one; assemble the records from them (inputs) and split them
   out (outputs); instantiate the real entity. Pass generics via per-side
   `configs` (VHDL `reset_time` vs Verilog `RESET_TIME`).

After `hierarchy -top <golden_top>; flatten`, the golden top exposes the flat
names, so `equiv_make` pairs ports by name and the inner record machinery becomes
internal. Manifest sketch:

```yaml
formal:
  modules:
    - name: spwlink
      golden_top: spwlink_flat
      candidate_top: spwlink
      wrapper: spwlink_flat.vhd
      configs:
        - golden: {reset_time: 640}
          candidate: {RESET_TIME: 640}
  bounded_depth: 40    # triage if induction can't close (BOUNDED vs real bug)
```

Alternatively the **`eqy` engine** (`formal.engine: eqy`) is meant to match
points across differing interfaces, but that path is **experimental and untested**
here — validate it before relying on it.

## Why bother being explicit

The flattening is the one place a translation can silently drop or swap a signal
and still compile on both sides. An explicit contract — checked by Layer 0 and
enforced by Layer 2's name-based port matching — turns that silent failure mode
into a hard error.
