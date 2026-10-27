# corpus/

Test cases. Each case is a folder:

```
<case>/
├── rtl/            source RTL
├── expected/       expected output at every layer boundary
│   ├── selection.json      L1 output
│   ├── diagram.json        L2 output
│   └── layout-hints.json   layout hints for L3
└── notes.md        which files are hand-written, who reviewed them
```

Fixtures let any layer run without its upstream: `rtl2d run corpus/<case> --fixture l1,l2`.

Rules: layer `src/` never reads this folder (only `pipeline/` and tests do).
Never edit `expected/` just to make a test pass. Report the failure instead.
