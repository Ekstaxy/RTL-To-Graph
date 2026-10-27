# x3: RTL → diagram tool comparison (pages)

Open any of these in a browser after cloning; each file is self-contained (every drawing is
embedded) and they link to each other.

- `index.html`: picosoc and darksocv top modules; ours vs 11 external tools, each in its default mode.
- `module-like.html`: one leaf module per SoC (spimemio_xfer, darkuart); every tool in its most
  minimal mode that still draws the structure.
- `recompare.html`: the top modules again, each tool with its own most-simplifying option,
  default and minimal side by side.

How they were made, the per-tool recipes and the findings:
`pipeline/experiments/x3_tool_compare/README.md`. Fonts load from Google Fonts when online;
offline, the pages fall back to system fonts.
