// RTL-To-Graph Agent 階段成果簡報：node make_deck.js data.json out.pptx
// 數字只讀 data.json（由 collect_deck_data.py 從稽核檔、對標檔、對話紀錄整理），截圖只讀 shots/。缺檔就停，不放假圖。
const fs = require("fs");
const path = require("path");
const pptxgen = require("pptxgenjs");

const D = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const OUT = process.argv[3] || "RTL-To-Graph_Agent_成果簡報.pptx";
const SHOTS = path.join(path.dirname(process.argv[2]), "shots");
const shot = (n) => {
  const p = path.join(SHOTS, n);
  if (!fs.existsSync(p)) throw new Error("missing screenshot " + p);
  return p;
};
const size = (p) => {  // PNG/JPEG pixel size, to keep aspect ratios
  const b = fs.readFileSync(p);
  if (b[0] === 0x89) return [b.readUInt32BE(16), b.readUInt32BE(20)];
  let i = 2;
  while (i < b.length) {
    const m = b[i + 1], len = b.readUInt16BE(i + 2);
    if (m >= 0xc0 && m <= 0xc3) return [b.readUInt16BE(i + 7), b.readUInt16BE(i + 5)];
    i += 2 + len;
  }
  return [16, 9];
};

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.333 x 7.5
pres.title = "RTL-To-Graph Agent 階段成果";
pres.theme = { headFontFace: "Microsoft JhengHei", bodyFontFace: "Microsoft JhengHei" };
const W = 13.333, H = 7.5;
const BG = "000000", FG = "FFFFFF", MUTE = "A5A5A5", ACC = "4ADE80", WARN = "FBBF24", BAD = "F87171", CARD = "15181D";

function base(label) {
  const s = pres.addSlide();
  s.background = { color: BG };
  if (label) s.addText(label, { x: 0.6, y: 0.35, w: 8, h: 0.4, fontSize: 16, color: MUTE, bold: true, margin: 0, isTextBox: true });
  return s;
}
function title(s, t, y = 0.8) {
  s.addText(t, { x: 0.6, y, w: W - 1.2, h: 0.9, fontSize: 38, bold: true, color: FG, margin: 0, isTextBox: true, fit: "shrink" });
}
function img(s, file, x, y, w, h) {  // fit inside the box, keep aspect
  const [iw, ih] = size(file);
  let ww = w, hh = (w * ih) / iw;
  if (hh > h) { hh = h; ww = (h * iw) / ih; }
  s.addImage({ path: file, x: x + (w - ww) / 2, y: y + (h - hh) / 2, w: ww, h: hh });
}
function tag(s, text, x, y, w, color) {
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h: 0.5, fill: { color }, rectRadius: 0.12, line: { color } });
  s.addText(text, { x, y, w, h: 0.5, fontSize: 18, bold: true, color: "000000", align: "center", valign: "middle", margin: 0, isTextBox: true });
}
function bullets(s, items, x, y, w, h, fontSize = 22) {
  s.addText(items.map((t, i) => ({ text: t, options: { bullet: true, breakLine: i < items.length - 1 } })),
    { x, y, w, h, fontSize, color: FG, paraSpaceAfter: 10, valign: "top", margin: 0, isTextBox: true });
}

// 1. 主張
let s = base("RTL-TO-GRAPH AGENT");
s.addText("一句話\n畫出一定正確的硬體圖", { x: 0.6, y: 1.6, w: 12, h: 2.6, fontSize: 54, bold: true, color: FG, margin: 0, isTextBox: true });
s.addText("AI agent 讀懂晶片設計程式碼，挑出該看的訊號，交給專案自己的管線畫出架構圖、狀態機與時序圖，每一條線都經過檢查", { x: 0.6, y: 4.6, w: 11.6, h: 1.2, fontSize: 24, color: MUTE, margin: 0, isTextBox: true });

// 2. 問題
s = base("01 / 要解決的問題");
title(s, "晶片程式碼難懂，現有工具畫的圖還會錯");
const P = D.problem;
[[P.lines, "行 Verilog", "一個小 SoC 的原始碼"], [P.tool_extra, "條不可能的轉移", "最好的開源工具 " + P.best_tool + " 畫在狀態圖上"], [P.tool_missed, "條真的會發生的轉移", "同一個工具漏畫"]].forEach(([n, u, c], i) => {
  const x = 0.6 + i * 4.15;
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 2.1, w: 3.85, h: 3.3, fill: { color: CARD }, rectRadius: 0.15, line: { color: CARD } });
  s.addText(String(n), { x: x + 0.3, y: 2.35, w: 3.3, h: 1.4, fontSize: 66, bold: true, color: i === 0 ? FG : BAD, margin: 0, isTextBox: true });
  s.addText(u, { x: x + 0.3, y: 3.75, w: 3.3, h: 0.6, fontSize: 24, bold: true, color: FG, margin: 0, isTextBox: true });
  s.addText(c, { x: x + 0.3, y: 4.4, w: 3.3, h: 0.8, fontSize: 20, color: MUTE, margin: 0, isTextBox: true });
});
s.addText("新人與審查者只能自己畫圖，畫錯也沒人知道。", { x: 0.6, y: 5.9, w: 12, h: 0.7, fontSize: 24, color: FG, margin: 0, isTextBox: true });

// 3. 做法
s = base("02 / AI AGENT 在做什麼");
title(s, "AI 負責理解與挑選，管線負責畫，檢查器負責裁決");
const flow = [["輸入端", "一句話", "想看哪個設計、哪種圖"], ["AI agent", "讀懂設計", "語意標註、讀原始碼、挑訊號"], ["專案管線", "畫三種圖", "架構圖、狀態機、時序圖"],
  ["檢查器", "證明與重播", "沒有證據的線不畫成事實"], ["輸出端", "圖與白話說明", "直接放進論文或簡報"]];
flow.forEach(([a, b, c], i) => {
  const x = 0.6 + i * 2.5;
  const col = i === 0 || i === 4 ? ACC : FG;
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 2.3, w: 2.2, h: 3.2, fill: { color: CARD }, rectRadius: 0.15, line: { color: i === 0 || i === 4 ? ACC : "3A4049", width: 1.5 } });
  s.addText(a, { x: x + 0.15, y: 2.45, w: 1.9, h: 0.5, fontSize: 18, bold: true, color: col, margin: 0, isTextBox: true });
  s.addText(b, { x: x + 0.15, y: 3.05, w: 1.9, h: 1.0, fontSize: 26, bold: true, color: FG, margin: 0, isTextBox: true });
  s.addText(c, { x: x + 0.15, y: 4.15, w: 1.9, h: 1.2, fontSize: 18, color: MUTE, margin: 0, isTextBox: true });
  if (i < 4) s.addShape(pres.shapes.RIGHT_TRIANGLE, { x: x + 2.25, y: 3.75, w: 0.2, h: 0.3, fill: { color: MUTE }, line: { color: MUTE }, rotate: 90 });
});
s.addText("AI 可以猜錯訊號，但猜錯只會讓圖變醜，不會讓圖變錯：每條線都要有模擬器重播的軌跡，或不可能發生的證明。", { x: 0.6, y: 5.9, w: 12.1, h: 1.0, fontSize: 22, color: FG, margin: 0, isTextBox: true });

// 4-8. 操作歷程，截圖與標註
for (const st of D.steps) {
  s = base(st.label);
  title(s, st.title);
  const f = shot(st.shot);
  img(s, f, 0.6, 1.85, st.note ? 8.4 : 12.1, 5.2);
  if (st.note) {
    tag(s, st.io, 9.3, 1.95, 3.4, st.io === "輸入端" ? ACC : st.io === "輸出端" ? WARN : "93C5FD");
    bullets(s, st.note, 9.3, 2.7, 3.45, 4.3, 20);
  }
}

// 9. 對標
s = base("03 / 和最好的開源工具正面比");
title(s, `${D.bench.n} 張狀態圖，完全畫對的張數`);
const B = D.bench.tools;
s.addChart(pres.charts.BAR, [{ name: "完全正確", labels: B.map((t) => t.name), values: B.map((t) => t.exact) }], {
  x: 0.6, y: 1.8, w: 7.6, h: 5.2, barDir: "bar", chartColors: B.map((t) => (t.ours ? "4ADE80" : "6B7280")),
  showValue: true, dataLabelPosition: "outEnd", dataLabelColor: "FFFFFF", dataLabelFontSize: 18, dataLabelFontFace: "Microsoft JhengHei",
  catAxisLabelColor: "FFFFFF", catAxisLabelFontSize: 16, catAxisLabelFontFace: "Microsoft JhengHei", valAxisHidden: true,
  valGridLine: { style: "none" }, catGridLine: { style: "none" }, valAxisMinVal: 0, valAxisMaxVal: D.bench.n, showLegend: false, barGapWidthPct: 40,
});
bullets(s, D.bench.notes, 8.6, 2.0, 4.2, 5.0, 20);

// 10. 可信
s = base("04 / 為什麼敢說一定正確");
title(s, "每一條線都帶著證據");
D.trust.forEach(([n, u, c], i) => {
  const x = 0.6 + (i % 2) * 6.15, y = 1.9 + Math.floor(i / 2) * 2.55;
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w: 5.9, h: 2.3, fill: { color: CARD }, rectRadius: 0.15, line: { color: CARD } });
  s.addText(String(n), { x: x + 0.3, y: y + 0.2, w: 2.4, h: 1.2, fontSize: 54, bold: true, color: ACC, margin: 0, isTextBox: true, fit: "shrink" });
  s.addText(u, { x: x + 2.7, y: y + 0.3, w: 3.0, h: 1.0, fontSize: 22, bold: true, color: FG, margin: 0, isTextBox: true, valign: "middle" });
  s.addText(c, { x: x + 0.3, y: y + 1.4, w: 5.3, h: 0.8, fontSize: 18, color: MUTE, margin: 0, isTextBox: true });
});

// 11. 差異
s = base("05 / 和既有產品哪裡不同");
title(s, "會畫圖的很多，畫對還拿得出證據的只有這個");
D.diff.forEach(([h, items, ours], i) => {
  const x = 0.6 + i * 4.15;
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 1.9, w: 3.85, h: 3.6, fill: { color: ours ? "052E16" : CARD }, rectRadius: 0.15, line: { color: ours ? ACC : CARD, width: 1.5 } });
  s.addText(h, { x: x + 0.3, y: 2.1, w: 3.3, h: 0.7, fontSize: 24, bold: true, color: ours ? ACC : FG, margin: 0, isTextBox: true });
  bullets(s, items, x + 0.3, 2.95, 3.3, 2.4, 20);
});

s.addText("差別不在會不會畫，而在畫出來的每一條線有沒有證據。", { x: 0.6, y: 5.95, w: 12.1, h: 0.8, fontSize: 26, bold: true, color: FG, margin: 0, isTextBox: true });

// 12. 限制
s = base("06 / 目前限制與待突破挑戰");
title(s, "照實記錄：還做不到的事");
bullets(s, D.limits, 0.6, 1.9, 12.1, 5.2, 21);

// 13. 下一步
s = base("07 / 下一步");
title(s, "從看得懂，到放心交給新人用");
bullets(s, D.next, 0.6, 1.9, 12.1, 4.2, 24);
s.addText("每一條線都有證據。", { x: 0.6, y: 6.1, w: 12, h: 0.8, fontSize: 32, bold: true, color: ACC, margin: 0, isTextBox: true });

pres.writeFile({ fileName: OUT }).then((f) => console.log("wrote", f));
