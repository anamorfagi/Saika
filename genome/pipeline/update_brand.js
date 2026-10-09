// Название программы: Anamorf Genom (решение владельца 15.09)
const fs=require("fs");let t=fs.readFileSync("gs.html","utf8");
t=t.replace("<title>Эльза Гранхирт — геном</title>","<title>Anamorf Genom</title>").replace(">Genome Studio<",">Anamorf Genom<").replace(/Genome Studio/g,"Anamorf Genom");
fs.writeFileSync("gs.html",t);console.log("brand ok");
