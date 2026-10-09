// update_probe.js — вшивает модуль «Ассистент · примерка образа» в genome-studio.html.
// Исходники модуля живут отдельно: pipeline/probe/probe.css и probe.js — правишь их, запускаешь этот скрипт снова.
// Вставка между маркерами, поэтому повторный запуск заменяет старую версию, а не дублирует.
const fs = require("fs"), path = require("path");
const P = path.join(__dirname, "genome-studio.html");
let h = fs.readFileSync(P, "utf8");
const css = fs.readFileSync(path.join(__dirname, "pipeline/probe/probe.css"), "utf8");
const js = fs.readFileSync(path.join(__dirname, "pipeline/probe/probe.js"), "utf8");
// защита: модуль с синтаксической ошибкой не вшивается — страница у владельца не должна ломаться
try { new (require("vm").Script)(js, { filename: "probe.js" }) } catch (e) { console.error("НЕ ВШИТО — ошибка в probe.js: " + e.message); process.exit(1) }
const A = "<!--PROBE-->", B = "<!--/PROBE-->";
const block = A + "<style id=\"probeCSS\">" + css + "</style><script id=\"probeJS\">" + js.replace(/<\/script/gi, "<\\/script") + "</script>" + B;
// спираль студии должна переезжать в модуль: центр и линия блоков становятся изменяемыми
h = h.replace("const CXF=0.66;", "let CXF=0.66;").replace("const BX=300;", "let BX=300;");
const i = h.indexOf(A), j = h.indexOf(B);
if (i >= 0 && j > i) h = h.slice(0, i) + block + h.slice(j + B.length);
else { const k = h.lastIndexOf("</body>"); if (k < 0) throw "нет </body>"; h = h.slice(0, k) + block + "\n" + h.slice(k); }
fs.writeFileSync(P, h);
fs.writeFileSync(path.join(__dirname, "ver.js"), 'window.__BUILD="' + new Date().toISOString() + '-probe";');
console.log("модуль вшит: css " + css.length + " · js " + js.length + " · html " + h.length);
