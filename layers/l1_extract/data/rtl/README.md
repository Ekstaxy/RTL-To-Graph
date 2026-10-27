# RTL snapshot（第三方原始碼）

這裡只收 L1 manifest 實際用到的 RTL 檔、include header 和 spec 文字檔（RTLLM），共 880 個檔案，約 8 MB。另外附上各 repo 原本的 LICENSE／COPYING／README。目錄結構和 `data/corpus/<repo>/` 完全相同，`outputs/teacher-v1` 裡的 `file` 路徑都指向這裡。

| repo | 授權 | commit |
|---|---|---|
| picorv32（含 picosoc） | ISC | 見 `scripts/fetch_corpus.py` |
| RTLLM | MIT | 同上 |
| verilog-eval | MIT | 同上 |
| verilog-axis／uart／i2c／axi／ethernet／wishbone | MIT | 同上 |
| serv | ISC | 同上 |
| darkriscv | BSD-3-Clause | 同上 |
| wb2axip | Apache-2.0（各檔案標頭有寫明） | 同上 |
| biriscv | Apache-2.0 | 同上 |
| common_cells | SolderPad Hardware License 0.51 | 同上 |

每個檔案都保留原作者的版權聲明。如果需要完整的 repo（testbench、文件），請執行：

```bash
python scripts/fetch_corpus.py
```

它會把完整 repo 下載到 `data/corpus/`，該目錄不進版控。
