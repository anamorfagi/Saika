// Add the live research controller after the studio definitions, before live reload.
const fs = require('fs');
const file = process.argv[2] || 'gs.html';
let text = fs.readFileSync(file, 'utf8');
if (!text.includes('function renderResearchCompiler()')) {
  const begin = text.indexOf('const cp=compilePrompt();');
  const end = text.indexOf('// ---------- голос: V-компилятор', begin);
  if (begin < 0 || end < 0) throw new Error('Compiler render boundaries missing');
  text = text.slice(0, begin) + 'function renderResearchCompiler(){\n["wtab","etab","dtab"].forEach(id=>document.querySelector("#"+id+" tbody").innerHTML="");\n' + text.slice(begin,end) + '}\nrenderResearchCompiler();\n' + text.slice(end);
}
text = text.replace('"voice","design","trace","trace_by"', '"voice","design","research","evidence","trace","trace_by"');
if (!text.includes('src="research-live.js')) {
  const marker = '<script>var __BUILD0=';
  if (!text.includes(marker)) throw new Error('No live-reload insertion point');
  text = text.replace(marker, '<script src="research-live.js?v=20260918-research1"></script>\n' + marker);
}
text = text.replace(/research-live\.js\?v=[^"']+/g, 'research-live.js?v=20260918-deepseekresearch1');
for (const match of text.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)) {
  if (!/\bsrc\s*=/.test(match[1]) && !/application\/json/.test(match[1])) new Function(match[2]);
}
fs.writeFileSync(file, text);
