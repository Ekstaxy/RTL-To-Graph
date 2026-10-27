# x4 intermediate formats (experiment-local, not contracts)

Every file below is JSON written under the git-ignored `runs/`. All three are produced and
consumed only by experiments; nothing in `src/` or `contracts/` reads them. FsmGraph v0.1
and TimingDiagram v0.1 are the L2 -> L3 formats (`fsm_spec.py`, `timing_spec.py`).

```
RTL ─L1 annotate_design (heuristic)─▶ graph.json, fsm.json, anchors.json      (L1 src, unchanged)
    ─e8_fsm_extra.extract──────────▶ fsm_ext.json                              (L1 experiment)
    ─e9_protocol_templates.select──▶ signals.json                              (L1 experiment)
fsm_ext.json ─x4 fsm_bridge──▶ FsmGraph ─x4 fsm_yosys / fsm_prove / fsm_check─▶ FsmGraph+checks
FsmGraph ─e4 fsm_draw─▶ SVG (+ round-trip)                                     (L3 experiment)
signals.json ─x4 tbgen + sim──▶ tb_gen.sv, wave.vcd, sim.json
signals.json + graph.json + wave.vcd + sim.json ─x4 timing_bridge──▶ TimingDiagram[]
TimingDiagram ─e4 wave_draw─▶ WaveDrom JSON ─wavedrom-cli─▶ SVG (+ round-trip) (L3 experiment)
```

Per design, x4 writes `runs/x4_fsm_timing/designs/<design>/`:
`l1/` (L1 outputs), `fsm_ext.json`, `signals.json`, `fsm/<module>.<state>.{json,svg,mmd,dot}`,
`sim/{tb_gen.sv,wave.vcd,sim.json,sim.log}`, `timing/<id>.{json,wavedrom.json,svg}`,
`formal/<module>.<state>/...`, `result.json`.

## Design entry (manifests and `--rtl DIR --top T`)
```jsonc
{"name": "orig_uart_tx", "files": ["layers/l1_extract/examples/rtl/uart_tx.sv"], "top": "uart_tx",
 "include_dirs": [], "defines": [], "tb": null}     // tb: optional path to an existing testbench
```
Paths are relative to the repo root (or absolute).

## fsm_ext.json (e8_fsm_extra, one list per design)
Each element is L1's `FSM.to_json()` with these keys added under `"extra"`:
```jsonc
{
  "module": "uart_tx", "instance": "uart_tx", "state": "state_q", "next": "state_d",
  "style": "two-process", "states": [{"name": "S_IDLE", "value": ""}], "reset_state": "S_IDLE",
  "transitions": [{"src": "S_IDLE", "dst": "S_START", "cond": "tx_valid"}],
  "outputs": [{"signal": "busy_o", "kind": "moore", "port": true}], "warnings": [],
  "semantic_check": "consistent", "semantic_transitions": [["S_IDLE","S_START"]],  // as L1 emits
  "extra": {
    "graph_key": "uart_tx.state_q",         // node key in graph.json
    "file": "/abs/path/uart_tx.sv", "decl_line": 25, "width": 2,
    "values": {"S_IDLE": 0, "S_START": 1},  // int value per state name (null if unknown)
    "encoding": "binary",                   // binary | onehot | gray | enum | other
    "unnamed": ["S_5"],                     // states whose name is the S_<v> fallback
    "reached": ["S_IDLE", "S_START"],       // reached by execution from reset; null if unknown
    "transition_lines": {"S_IDLE->S_START": [{"file": "...", "line": 41}]},
    "reset_line": {"file": "...", "line": 33},
    "outputs_semantic": null,               // for semantic-only FSMs: [{signal, kind, port}]
    "engine": "l1-hybrid",                  // or "e8-counter" for counter-driven FSMs (M4)
    "provenance": {"seed": 0, "time_budget": 60.0, "budget_exhausted": false}
  }
}
```

## signals.json (e9_protocol_templates, one object per design, top module only)
```jsonc
{
  "design": "sync_fifo", "top": "sync_fifo",
  "clocks": [{"port": "clk", "domain": "d.clk", "edge": "posedge", "line": 6}],
  "resets": [{"port": "rst_n", "active_low": true, "sync": false, "domains": ["d.clk"], "line": 7}],
  "interfaces": [{
    "id": "if.in", "name": "in", "protocol": "VALID_READY",  // VALID_READY|REQ_ACK|STREAM|MEMORY_BUS|SERIAL|FIFO|SIMPLE
    "direction": "in",           // in: the design consumes (valid is an input); out: it produces
    "domain": "d.clk",           // or "cdc" when members span domains
    "confirmed": true,           // structural template matched on the graph
    "members": [{"port": "in_valid", "role": "valid", "width": 1, "dir": "in", "domain": "d.clk", "line": 9}],
    "evidence": ["in_ready gates write of mem_q (always_ff@L33)"],
    "demoted_reason": null
  }],
  "internal": [{"signal": "count_q", "key": "sync_fifo.count_q", "width": 5, "domain": "d.clk",
                "role": "state|reg", "line": 20, "near": ["if.in"], "reason": "2 hops from in_valid"}],
  "other_inputs": [{"port": "flush_i", "width": 1, "domain": "d.clk", "line": 8, "kind": "control|data"}],
  "dropped": [{"signal": "mem_q", "line": 18, "reason": "memory (depth 16)"}]
}
```
Roles: `valid ready data req ack addr we wdata rdata wr rd full empty serial tick enable`.
`other_inputs` lists top input ports that are in no interface and are not clock/reset, so the
testbench generator can drive them (control: held at 0 after reset unless a template says otherwise).

## sim.json (x4 sim, one per design)
```jsonc
{
  "kind": "generated",          // tb | generated | cover
  "tb_path": "runs/.../sim/tb_gen.sv", "tb_top": "tb", "dut_path": "tb.dut",
  "seed": 1, "simulator": "iverilog", "version": "Icarus Verilog version 14.0 ...",
  "cmd": [["iverilog", "..."], ["vvp", "..."]], "warnings": [],
  "vcd": "runs/.../sim/wave.vcd", "vcd_sha256": "…", "timescale": "1ns",
  "clocks": [{"port": "clk", "domain": "d.clk", "period": 10, "phase": 5}],
  "resets": [{"port": "rst_n", "active_low": true, "release_t": 35}],
  "end_t": 4000, "ok": true, "error": null
}
```
VCD naming: testbench top `tb`, DUT instance `dut`, so a top port `in_valid` is `tb.dut.in_valid`
and an internal register `count_q` is `tb.dut.count_q`.
