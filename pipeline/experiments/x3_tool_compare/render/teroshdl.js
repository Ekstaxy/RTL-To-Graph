// TerosHDL schematic, as src/teroshdl/features/schematic.ts does it: normalizeNetlist, then
// the TerosTechnology/netlistsvg#hierarchy fork with the extension's default.svg skin and config.
// usage: node teroshdl.js <netlistsvg fork dir> <skin.svg> <in.json> <out.svg> [hierarchy mode]
// The extension hard-codes hierarchy.enable "all"; x3's minimal run passes "off", the fork's own
// default (lib/config.json; README "hierarchy": off / level / all / modules).
const fs = require("fs");
const path = require("path");

const [forkDir, skinPath, inPath, outPath, mode = "all"] = process.argv.slice(2);
const netlistsvg = require(path.resolve(forkDir));

function normalizeNetlist(netlist) {
  for (const name in netlist.modules) {
    const cells = netlist.modules[name].cells;
    for (const c in cells) {
      if (cells[c].port_directions === undefined) {
        cells[c].port_directions = {};
        for (const port in cells[c].connections) cells[c].port_directions[port] = "input";
      }
    }
  }
  return netlist;
}

const config = {
  hierarchy: {
    enable: mode,
    expandLevel: 0,
    expandModules: { types: [], ids: [] },
    colour: ["#e9e9e9"],
  },
  top: { enable: false, module: "" },
};

const skin = fs.readFileSync(skinPath);
const netlist = normalizeNetlist(JSON.parse(fs.readFileSync(inPath, "utf8")));
netlistsvg.render(skin, netlist, undefined, undefined, config).then(
  (svg) => fs.writeFileSync(outPath, svg),
  (err) => {
    console.error(err);
    process.exit(1);
  },
);
