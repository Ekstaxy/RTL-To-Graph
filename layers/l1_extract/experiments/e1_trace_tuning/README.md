# e1_trace_tuning

**Owner:** L1（薛晏閎）　**Date:** 2026-10-01

## Hypothesis
Trace 的 region 由 cost-bounded slicing 決定，參數是各 level 的閾值和 TAU。調這兩個參數可以做到：MEDIUM 有明顯降噪（內部節點 reduction ≥ 0.6），同時不把 minor anchor 大量帶進 region（leak 低）。

## Measurement
- 輸入：`examples/corpus.json` 和 `data/corpus/{rtllm,verilog_eval,picorv32}.json` 的 teacher 標註，從 Run Store 讀。
- 每組閾值／TAU 量兩個數：
  - internal reduction 的中位數；
  - leak：低一級的 anchor 被收進 region 的比例。
- 加 `--ablate` 時，另外比較拿掉 Steiner、拿掉 closure 的效果。

```bash
python experiments/e1_trace_tuning/run.py examples/corpus.json data/corpus/rtllm.json data/corpus/verilog_eval.json data/corpus/picorv32.json [--ablate]
```

## Pass / abandon criteria
- 通過：MEDIUM reduction ≥ 0.6，且 HIGH 的 leak 明顯低於 v1.3 的預設。
- 放棄：沒有任何一組同時滿足這兩個條件。

## Results
選定 HIGH／MEDIUM／LOW = 0.60／0.40／0.15，TAU = 1.5，Steiner 預設關閉。詳見 `docs/VALIDATION.md` §4.3。

## Conclusion
已併入 `src/rtl2d_l1/trace.py` 的預設值（SPEC v1.3）。
