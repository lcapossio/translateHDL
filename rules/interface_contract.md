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

## When names can't be made to match

If the golden VHDL keeps record ports and you can't rename them, give the formal
layer help in one of two ways:

1. **Wrapper** (per-module `formal.modules[].wrapper`): a tiny Verilog module
   with the candidate's flattened port names that instantiates the
   GHDL-synthesized golden netlist and wires record fields to flat ports. The
   golden side then presents the same interface as the candidate.
2. **eqy engine** (`formal.engine: eqy`): YosysHQ eqy can match equivalent points
   across differing interfaces via its partitioning/`[match]` mechanism.

## Why bother being explicit

The flattening is the one place a translation can silently drop or swap a signal
and still compile on both sides. An explicit contract — checked by Layer 0 and
enforced by Layer 2's name-based port matching — turns that silent failure mode
into a hard error.
