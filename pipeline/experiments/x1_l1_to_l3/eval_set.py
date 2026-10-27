"""Held-out evaluation set: designs from the L1 corpus, none of them written by us.

The split is fixed before anything is drawn. Inside each category, designs are ordered by
the sha1 of their name and alternate dev / test. Fixes may look at dev only. Test is run once
per frozen version, and nothing is changed because of a test result.

    python pipeline/experiments/x1_l1_to_l3/eval_set.py   -> eval_set.json
"""

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
CORPUS = HERE.parents[2] / "layers/l1_extract/data/corpus"

CATEGORIES = {
    "cpu_hier": [
        "picorv32_picosoc",
        "dark_darksocv",
        "serv_serv_top",
        "serv_serv_rf_top",
        "biriscv_biriscv_issue",
        "picorv32_axi",
    ],
    "cpu_flat": ["picorv32", "dark_darkriscv", "biriscv_biriscv_divider", "biriscv_biriscv_csr"],
    "network": [
        "verilog-ethernet_udp_complete",
        "verilog-ethernet_eth_mac_1g_rgmii_fifo",
        "verilog-ethernet_ip_complete",
        "verilog-ethernet_arp",
        "verilog-ethernet_eth_mac_phy_10g",
        "verilog-ethernet_udp",
    ],
    "bus": [
        "verilog-axi_axi_crossbar",
        "verilog-axi_axil_crossbar_rd",
        "wb2axip_axim2wbsp",
        "wb2axip_axisgdma",
        "verilog-axi_axi_vfifo",
        "verilog-axis_axis_ram_switch",
    ],
    "cdc_fifo": [
        "common_cells_cc_cdc_fifo_gray",
        "common_cells_cc_cdc_2phase_clearable",
        "common_cells_cc_cdc_reset_ctrlr",
        "common_cells_cc_mem_to_banks",
        "rtllm_asyn_fifo",
        "verilog-axis_axis_fifo_adapter",
    ],
    "peripheral": [
        "verilog-uart_uart",
        "verilog-i2c_i2c_master_axil",
        "verilog-i2c_i2c_master",
        "verilog-uart_uart_rx",
    ],
    "arith": ["rtllm_adder_32bit", "rtllm_adder_16bit", "rtllm_adder_pipe_64bit"],
}
# never seen during development or the first blind round; for the second blind round only
FRESH = [
    "verilog-ethernet_eth_mac_10g_fifo",
    "wb2axip_axidouble",
    "verilog-i2c_i2c_master_wbs_8",
    "common_cells_cc_stream_omega_net",
    "biriscv_biriscv_lsu",
    "common_cells_cc_cdc_fifo_gray_clearable",
    "verilog-wishbone_wb_arbiter_2",
    "picorv32_wb",
]


def main() -> None:
    man = {}
    for f in sorted(CORPUS.glob("*.json")):
        for it in json.loads(f.read_text(encoding="utf-8")):
            man.setdefault(it["name"], it)
    out = []
    for cat, names in CATEGORIES.items():
        for i, n in enumerate(sorted(names, key=lambda s: hashlib.sha1(s.encode()).hexdigest())):
            it = man[n]
            out.append(
                {
                    "name": n,
                    "category": cat,
                    "split": "dev" if i % 2 == 0 else "test",
                    "top": it["top"],
                    "files": [f"data/corpus/{f}" for f in it["files"]],
                }
            )
    for n in FRESH:
        it = man[n]
        out.append(
            {
                "name": n,
                "category": "fresh",
                "split": "fresh",
                "top": it["top"],
                "files": [f"data/corpus/{f}" for f in it["files"]],
            }
        )
    # our own CPU: an indicator scored like everything else, never part of dev or test
    out.append(
        {
            "name": "rv32i_5stage",
            "category": "indicator",
            "split": "indicator",
            "top": "rv32i_core",
            "files": [
                "../../pipeline/experiments/x1_l1_to_l3/rtl/rv32i_5stage/rv_units.sv",
                "../../pipeline/experiments/x1_l1_to_l3/rtl/rv32i_5stage/rv32i_core.sv",
            ],
        }
    )
    (HERE / "eval_set.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    for s in ("dev", "test"):
        print(s, [d["name"] for d in out if d["split"] == s])


if __name__ == "__main__":
    main()
