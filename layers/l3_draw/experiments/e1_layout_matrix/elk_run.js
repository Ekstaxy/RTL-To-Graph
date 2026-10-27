// Reads one ELK graph (JSON) on stdin, writes the laid-out graph on stdout.
const ELK = require(process.argv[2]);
let buf = "";
process.stdin.on("data", (c) => (buf += c));
process.stdin.on("end", () => {
  new ELK()
    .layout(JSON.parse(buf))
    .then((g) => process.stdout.write(JSON.stringify(g)))
    .catch((e) => {
      process.stderr.write(String(e && e.message ? e.message : e));
      process.exit(1);
    });
});
