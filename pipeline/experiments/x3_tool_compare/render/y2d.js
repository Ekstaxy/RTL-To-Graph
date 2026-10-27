// yosys2digitaljs as its process.js CLI runs it (default options, fsm on, io_ui), with one change:
// the script's `hierarchy -auto-top` becomes `hierarchy -top <top>`, because the tool has no
// top option and picorv32.v holds several candidate tops.
// usage: node y2d.js <yosys2digitaljs dir> <yosys> <top> <out.json> <file.v>...
const fs = require("fs");
const os = require("os");
const path = require("path");
const { execSync } = require("child_process");

const [dir, yosys, top, outPath, ...files] = process.argv.slice(2);
const core = require(path.resolve(dir, "dist/core.js"));

const script = core
  .prepare_yosys_script(files, { fsm: true })
  .replace("hierarchy -auto-top", `hierarchy -top ${top}`);
const tmp = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "y2d-")), "yosys.json");
// same shell command line as src/index.ts process() (the script is escaped for a shell)
execSync(`${yosys} -q -p "${script}" -o ${tmp}`, { stdio: ["ignore", "inherit", "inherit"] });
const out = core.yosys2digitaljs(JSON.parse(fs.readFileSync(tmp, "utf8")), { fsm: true });
core.io_ui(out);
fs.writeFileSync(outPath, JSON.stringify(out));
console.log(script);
