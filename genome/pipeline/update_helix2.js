// update_helix2.js — спираль: знак гена читается положением. Ось (0) — центр перекладины; положительные гены уходят к правой
// (на экране) нити и окрашены золотом, отрицательные — к левой, цвет комплиментарный (холодный бирюзово-синий).
// По окрашенной части идут лёгкие импульсы (блики) — живая нить. Предполагаемое — пунктир от оси в свою сторону.
// Запуск: node update_helix2.js (после update_dna). Правит gs.html.
const fs=require("fs");let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("не найдено:",a.slice(0,80));process.exit(1)}t=t.replace(a,b)}

// [1] позиция бусины: от оси к правой нити при v>0, к левой при v<0; длина = |v|
rep(`      const frac=.1+Math.abs(G.v)*.8; // бусина всегда идёт от одной нити; знак — цветом
      const bx=x1+(x2-x1)*frac,bz=z1+(z2-z1)*frac;`,
`      // правая на экране нить — та, у которой мировой x больше (экранный x растёт с мировым); v>0 → к ней, v<0 → к левой
      const rx=x1>x2?x1:x2,rz=x1>x2?z1:z2;const dirv=G.v>=0?1:-1;const len=Math.abs(G.v);
      const bx=rx*dirv*len,bz=rz*dirv*len;
      const pdir=G.pv>=0?1:-1,plen=Math.abs(G.pv||0);const px=rx*pdir*plen,pz=rz*pdir*plen;`);
rep(`items.push({t:"rung",G,k,x1,z1,x2,z2,yy,bx,bz,z:(z1+z2)/2});`,`items.push({t:"rung",G,k,x1,z1,x2,z2,yy,bx,bz,px,pz,z:(z1+z2)/2});`);

// [2] отрисовка перекладины: серый остов целиком, цветная часть от оси, пунктир предположения от оси, импульс
const r0=t.indexOf(`    else if(it.t==="rung"){`),r1=t.indexOf(`    else if(it.t==="bead"){`,r0);
if(r0<0||r1<0){console.error("нет ветки rung");process.exit(1)}
t=t.slice(0,r0)+`    else if(it.t==="rung"){
      const [ax,ay]=proj(it.x1,it.yy,it.z1),[bx2,by2]=proj(it.x2,it.yy,it.z2),[cx,cy,s]=proj(it.bx,it.yy,it.bz),[ox,oy]=proj(0,it.yy,0);it.G._r={x1:it.x1,z1:it.z1,bx:it.bx,bz:it.bz,yy:it.yy};
      const G=it.G,isSel=G.i===sel,isHov=G.i===hover,dimB=(overview||G.bi===curB)?1:.1,a=(.18+depth*.45)*(.35+G.c*.65)*dimB;
      ctx.lineWidth=(isSel?2.2:1)*s;ctx.strokeStyle=\`rgba(233,226,236,\${a*.45})\`;ctx.beginPath();ctx.moveTo(ax,ay);ctx.lineTo(bx2,by2);ctx.stroke();
      // предполагаемая нить: пунктир от оси в сторону знака предположения
      if(G.pc>0&&(G.c===0||Math.abs(G.pv-G.v)>=.1)){const [qx,qy]=proj(it.px,it.yy,it.pz);const pcol=G.pv>=0?SIGN_POS:SIGN_NEG;
        ctx.save();ctx.setLineDash([3*s,3*s]);ctx.lineWidth=1.8*s;ctx.strokeStyle=\`rgba(\${pcol},\${Math.min(1,(a+.3)*(.6+G.pc))})\`;ctx.beginPath();ctx.moveTo(ox,oy);ctx.lineTo(qx,qy);ctx.stroke();ctx.restore();
        if(G.c===0){ctx.fillStyle=\`rgba(\${pcol},\${(.4+depth*.4)*(.5+G.pc)*dimB})\`;ctx.beginPath();ctx.arc(qx,qy,(1.1+Math.abs(G.pv)*1.1)*s,0,7);ctx.fill()}}
      // снятое: от оси к бусине, цвет — знак
      if(G.c>0){const col=G.v>=0?SIGN_POS:SIGN_NEG;ctx.lineWidth=(isSel||isHov?3.4:2.2)*s;ctx.strokeStyle=\`rgba(\${col},\${Math.min(1,a+.25)})\`;ctx.beginPath();ctx.moveTo(ox,oy);ctx.lineTo(cx,cy);ctx.stroke();
        // импульс: короткий яркий блик бежит от оси к бусине; фаза своя у каждого гена, скорость — по уверенности
        if(Math.abs(G.v)>=.1&&dimB>.5){const T=performance.now()/1000;const ph=((T*(.25+G.c*.35)+G.i*.173)%1);const L=Math.hypot(cx-ox,cy-oy);if(L>6){const ux=(cx-ox)/L,uy=(cy-oy)/L;const p0=L*ph,p1=Math.min(L,p0+Math.max(6,L*.14));
          const g=ctx.createLinearGradient(ox+ux*p0,oy+uy*p0,ox+ux*p1,oy+uy*p1);g.addColorStop(0,\`rgba(255,250,240,0)\`);g.addColorStop(.6,\`rgba(255,250,240,\${(.35+G.c*.45)*dimB})\`);g.addColorStop(1,\`rgba(255,250,240,0)\`);
          ctx.lineWidth=(isSel||isHov?3.4:2.2)*s;ctx.strokeStyle=g;ctx.beginPath();ctx.moveTo(ox+ux*p0,oy+uy*p0);ctx.lineTo(ox+ux*p1,oy+uy*p1);ctx.stroke()}}}
    }
`+t.slice(r1);
// [3] бусина: цвет — знак (серые неснятые стоят на оси)
rep(`const col=G.c===0?"140,132,150":toneRGB(G);const r=(1.2+Math.abs(G.v)*1.3)*s*(isSel?1.35:isHov?1.2:1);const dimB=(overview||G.bi===curB)?1:.1;`,
`const col=G.c===0?"140,132,150":(G.v>=0?SIGN_POS:SIGN_NEG);const r=(1.2+Math.abs(G.v)*1.3)*s*(isSel?1.35:isHov?1.2:1);const dimB=(overview||G.bi===curB)?1:.1;`);
// [4] константы цвета знака: золото для +, комплиментарный холодный для −
rep(`const proj=(x,yy,z)=>{`,`const SIGN_POS="207,174,112",SIGN_NEG="96,168,214"; // +1 золото · −1 комплиментарный (холодный голубой)
const proj=(x,yy,z)=>{`);
// [5] энергия по нитям: по белому остову вверх бегут блики (несколько на виток), ярче ближе к зрителю
rep(`ctx.strokeStyle=\`rgba(233,226,236,\${(.10+depth*.38)*dimS})\`;ctx.lineWidth=(1.2+depth*2.2)*s;ctx.lineCap="round";ctx.beginPath();ctx.moveTo(ax,ay);ctx.lineTo(bx,by);ctx.stroke();}`,
`ctx.strokeStyle=\`rgba(233,226,236,\${(.10+depth*.38)*dimS})\`;ctx.lineWidth=(1.2+depth*2.2)*s;ctx.lineCap="round";ctx.beginPath();ctx.moveTo(ax,ay);ctx.lineTo(bx,by);ctx.stroke();
      {const T=performance.now()/1000;const side=it.ax*it.bz-it.az*it.bx>=0?0:.5;let ph=(((it.ay+cam.y)/LOOP)*2.5-T*.35+side)%1;if(ph<0)ph+=1;
        if(ph<.10){const k=1-ph/.10;ctx.strokeStyle=\`rgba(255,250,240,\${(.15+depth*.5)*k*dimS})\`;ctx.lineWidth=(1.6+depth*2.6)*s;ctx.beginPath();ctx.moveTo(ax,ay);ctx.lineTo(bx,by);ctx.stroke()}}}`);
fs.writeFileSync("gs.html",t);console.log("helix2 ok");
