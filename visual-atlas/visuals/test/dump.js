// Regenerates test/data.json from the gallery's sample data: node visuals/test/dump.js
const fs=require('fs'),vm=require('vm');const path=require('path');const S=path.resolve(__dirname,'../../gallery/src')+'/';
const ctx=vm.createContext({console,Math,JSON,Object,Array,String,Number,Date,Map,Set,isNaN});
vm.runInContext(['geo.js','data.js','layouts.js','engine.js','engine-maps.js','engine-html.js','engine-x1.js','engine-x2.js','glyphs.js','catalog.js','catalog-x.js'].map(f=>fs.readFileSync(S+f,'utf8')).join('\n;\n')+'\nthis.__={X_SK,X_PNL,X_BRANDS,X_SWITCH,X_TRADE,NET,HD,HP,TY,LY,MON,CH,CHM,REG4,REGCH,CAT4,SUBS};',ctx);
const X=ctx.__;const rows=(o)=>o.links.map(l=>[o.nodes[l.s].n,o.nodes[l.t].n,l.v]);
const chordRows=(names,m)=>{const r=[];m.forEach((row,i)=>row.forEach((v,j)=>{if(v)r.push([names[i],names[j],v]);}));return r;};
const net=X.NET.links.map(l=>[X.NET.nodes[l.s].n,X.NET.nodes[l.t].n,l.w]);
// date hierarchy for drill: rows of [year, quarter, month, sales, profit] from HD
const hd=[];const walk=(n,path)=>{if(!n.c){hd.push([...path,n.n,n.v[0],n.v[1]]);return;}n.c.forEach(c=>walk(c,[...path,n.n]));};X.HD.root.c.forEach(y=>walk(y,[]));
const hp=[];const walkp=(n,path)=>{if(!n.c){hp.push([...path,n.n,n.v[0],n.v[1]]);return;}n.c.forEach(c=>walkp(c,[...path,n.n]));};X.HP.root.c.forEach(y=>walkp(y,[]));
const chan=[];X.MON.forEach((m,i)=>X.CH.forEach((c,k)=>chan.push([m,c,X.CHM[k][i]])));
fs.writeFileSync(path.join(__dirname,'data.json'),JSON.stringify({traffic:rows(X.X_SK),pnl:rows(X.X_PNL),switching:chordRows(X.X_BRANDS,X.X_SWITCH),trade:chordRows(X.X_TRADE.names,X.X_TRADE.m),net,hd,hp,chan,months:X.MON}));
console.log('rows',rows(X.X_SK).length,rows(X.X_PNL).length,net.length,hd.length,hp.length,chan.length, hd[0], hp[0]);
