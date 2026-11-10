/* ============================================================
   Maps: world (Mercator) and US (Albers) basemaps with live
   zoom / pan state (st.k, st.tx, st.ty) and drill-to-zoom
   ============================================================ */

function mapView(G,W,H,st,o){
  const sy=o.pitch||1,s0=Math.min(W/G.w,H/(G.h*sy))*(o.fit||.98);
  const ox=(W-G.w*s0)/2,oy=(H-G.h*s0*sy)/2;
  const k=st.k||1,tx=st.tx||0,ty=st.ty||0;
  const P=([x,y])=>[(x*s0+ox)*k+tx,(y*s0*sy+oy)*k+ty];
  return {s0,sy,ox,oy,k,P,tf:`translate(${n1(ox*k+tx)},${n1(oy*k+ty)}) scale(${(s0*k).toFixed(4)},${(s0*k*sy).toFixed(4)})`};
}
/* view that frames a source-space bbox [x0,y0,x1,y1] */
function mapFit(G,W,H,o,b){
  const v=mapView(G,W,H,{},o);
  const bw=Math.max(8,(b[2]-b[0]))*v.s0,bh=Math.max(8,(b[3]-b[1]))*v.s0*v.sy;
  const k=Math.max(1,Math.min(7,Math.min(W/bw,H/bh)*.78));
  const cx=((b[0]+b[2])/2)*v.s0+v.ox,cy=((b[1]+b[3])/2)*v.s0*v.sy+v.oy;
  return {k,tx:W/2-cx*k,ty:H/2-cy*k};
}
const regOfCity=n=>CITIES.find(c=>c.n===n);
function worldPoints(o,st){
  const C=GEO.world.cities;
  if(o.layer==='drill'){
    const path=st.path||[];
    if(!path.length)return HG.root.c.map((r,i)=>{const cs=leaves(r).map(c=>C[c.n]);return {n:r.n,at:[sumA(cs.map(c=>c[0]))/cs.length,sumA(cs.map(c=>c[1]))/cs.length],v:agg(r)[0],g:i,i,d:true};});
    const r=HG.root.c[path[0]];return leaves(r).map((c,i)=>({n:c.n,at:C[c.n],v:c.v[0],g:path[0],i}));
  }
  return CITIES.map((c,i)=>({n:c.n,at:C[c.n],v:c.v[0],ly:c.v[2],g:REG4.indexOf(c.reg),i,reg:c.reg}));
}
function worldBBox(o,st){const pts=worldPoints(o,st);const xs=pts.map(p=>p.at[0]),ys=pts.map(p=>p.at[1]);return [Math.min(...xs)-30,Math.min(...ys)-30,Math.max(...xs)+30,Math.max(...ys)+30];}
function usPoints(){return Object.entries(GEO.us.cities).map(([n,at],i)=>({n,at,v:USCITYV[n],i,g:i%3}));}
function heatDefs(id){return `<radialGradient id="${id}"><stop offset="0" style="stop-color:var(--heat3);stop-opacity:.9"/><stop offset=".35" style="stop-color:var(--heat2);stop-opacity:.6"/><stop offset="1" style="stop-color:var(--heat1);stop-opacity:0"/></radialGradient>`;}
function miniPie(cx,cy,r,vals,i,title){
  const t=sumA(vals);let a=-Math.PI/2,s='';
  vals.forEach((v,k)=>{const b=a+v/t*Math.PI*2;const x0=cx+r*Math.cos(a),y0=cy+r*Math.sin(a),x1=cx+r*Math.cos(b),y1=cy+r*Math.sin(b);
    s+=`<path d="M${n1(cx)},${n1(cy)}L${n1(x0)},${n1(y0)}A${n1(r)},${n1(r)} 0 ${b-a>Math.PI?1:0},1 ${n1(x1)},${n1(y1)}Z" style="fill:${col(k+1)}"/>`;a=b;});
  return `<g class="mp" data-i="${i}" data-t="${tipA(title,vals.map((v,k)=>[fmt(v,'$'),CH[k],k+1]))}">${s}<circle cx="${n1(cx)}" cy="${n1(cy)}" r="${n1(r)}" class="ring"/></g>`;
}
function bubbleLegend(x,y,fs,vmax,rmax){
  const vs=[vmax,vmax/4];let s=`<g class="blg">`;vs.forEach((v,k)=>{const r=Math.sqrt(v/vmax)*rmax;s+=`<circle cx="${n1(x+rmax)}" cy="${n1(y+rmax*2-r)}" r="${n1(r)}"/><text x="${n1(x+rmax*2+5)}" y="${n1(y+rmax*2-r*2+fs*.36+(k?2:0))}" class="lg">${fmt(v,'$')}</text>`;});return s+'</g>';
}
function overlayLegend(items,x,y,fs){
  const w=Math.max(...items.map(i=>TW(i.n,fs)))+28,h=items.length*(fs+6)+8;
  let s=`<rect class="olg" x="${n1(x)}" y="${n1(y)}" width="${n1(w)}" height="${n1(h)}" rx="6"/>`;
  items.forEach((it,k)=>{const yy=y+8+k*(fs+6)+fs*.75;s+=`<circle cx="${n1(x+10)}" cy="${n1(yy-fs*.35)}" r="4.5" style="fill:${col(it.c)}"/><text x="${n1(x+19)}" y="${n1(yy)}" class="lg">${esc(it.n)}</text>`;});
  return s;
}

E.wmap={
  draw(o,st,W,H){
    const fs=FS(W),G=GEO.world,v=mapView(G,W,H,st,o);
    let s=`<rect class="water" width="${W}" height="${H}"/><g class="landg" transform="${v.tf}"><path class="land" d="${G.land}"/></g>`;
    let lay='',defs='';
    const pts=worldPoints(o,st);const vmax=Math.max(...pts.map(p=>p.v));
    const rmax=(W>=560?30:17)*(o.layer==='drill'&&!(st.path||[]).length?1.25:1);
    const R=p=>Math.max(3,Math.sqrt(p.v/vmax)*rmax);
    if(o.layer==='heat'){const id='hg'+(++UID);defs+=heatDefs(id);
      pts.forEach(p=>{const [x,y]=v.P(p.at);lay+=`<circle cx="${n1(x)}" cy="${n1(y)}" r="${n1(R(p)*2.3*Math.sqrt(v.k))}" fill="url(#${id})" class="heat"/>`;});
      pts.forEach(p=>{const [x,y]=v.P(p.at);lay+=`<circle class="hit" data-i="${p.i}" cx="${n1(x)}" cy="${n1(y)}" r="10" data-t="${tipA(p.n,[[fmt(p.v,'$'),'Sales','heat3']])}"/>`;});}
    else if(o.layer==='cluster'){
      const cell=W>=560?70:46;const cl=new Map();
      pts.forEach(p=>{const [x,y]=v.P(p.at);const key=Math.floor(x/cell)+','+Math.floor(y/cell);if(!cl.has(key))cl.set(key,[]);cl.get(key).push({...p,x,y});});
      cl.forEach(arr=>{const x=sumA(arr.map(a=>a.x))/arr.length,y=sumA(arr.map(a=>a.y))/arr.length;
        if(arr.length===1){const p=arr[0];lay+=`<circle class="bub" data-i="${p.i}" cx="${n1(x)}" cy="${n1(y)}" r="5" style="fill:var(--c1)" data-t="${tipA(p.n,[[fmt(p.v,'$'),'Sales',1]])}"/>`;}
        else{const r=9+Math.sqrt(arr.length)*4;lay+=`<g class="clu" data-z="${n1(x)},${n1(y)}" data-t="${tipA(arr.length+' locations',[[fmt(sumA(arr.map(a=>a.v)),'$'),'Sales',1],['Click to zoom in','','muted']])}"><circle cx="${n1(x)}" cy="${n1(y)}" r="${n1(r+5)}" class="clu-h"/><circle cx="${n1(x)}" cy="${n1(y)}" r="${n1(r)}" style="fill:var(--c1)"/><text x="${n1(x)}" y="${n1(y+fs*.36)}" text-anchor="middle" class="li">${arr.length}</text></g>`;}});}
    else if(o.layer==='path'){
      const hub=GEO.world.cities['Amsterdam'];const [hx,hy]=v.P(hub);
      const dests=['New York','São Paulo','Dubai','Mumbai','Singapore','Tokyo','Sydney','Johannesburg','Toronto','Lagos'];
      dests.forEach((d,i)=>{const c=CITIES.find(x=>x.n===d);const [x,y]=v.P(GEO.world.cities[d]);const mx=(hx+x)/2,my=(hy+y)/2-Math.hypot(x-hx,y-hy)*.22;const w=1+c.v[0]/vmax*3.4;
        lay+=`<path class="route" data-i="${i}" d="M${n1(hx)},${n1(hy)}Q${n1(mx)},${n1(my)} ${n1(x)},${n1(y)}" stroke-width="${n1(w)}" data-t="${tipA('Amsterdam → '+d,[[fmt(c.v[0]/38,'')+' t','Shipped volume',1]])}"/><circle cx="${n1(x)}" cy="${n1(y)}" r="3.5" class="dest"/>`;});
      lay+=`<circle cx="${n1(hx)}" cy="${n1(hy)}" r="6" class="hub"/><text x="${n1(hx+8)}" y="${n1(hy-6)}" class="lb">Amsterdam DC</text>`;}
    else if(o.layer==='pie'){
      const sel=CITIES.filter(c=>c.v[0]>480000);
      sel.forEach((c,i)=>{const [x,y]=v.P(GEO.world.cities[c.n]);const r=Math.max(6,Math.sqrt(c.v[0]/vmax)*rmax*.9);const vals=CH.map((_,k)=>Math.round(c.v[0]*[.44,.38,.18][k]*(.75+((c.n.length*(k+3))%7)/14)));lay+=miniPie(x,y,r,vals,i,c.n);});
      lay+=overlayLegend(CH.map((n,k)=>({n,c:k+1})),6,6,fs);}
    else if(o.layer==='marker'){
      pts.forEach(p=>{const [x,y]=v.P(p.at);const c=col(p.g+1);lay+=`<g class="pin" data-i="${p.i}" data-t="${tipA(p.n,[[fmt(p.v,'$'),'Sales',p.g+1],[p.reg,'Region','muted']])}" transform="translate(${n1(x)},${n1(y)})"><path d="M0,0C-2,-5 -7,-8 -7,-13A7,7 0 1,1 7,-13C7,-8 2,-5 0,0Z" style="fill:${c}"/><circle cy="-13" r="2.6" class="pin-dot"/></g>`;});
      lay+=overlayLegend(REG4.map((n,k)=>({n,c:k+1})),6,6,fs);}
    else{ /* bubbles (default and drill) */
      const sorted=pts.slice().sort((a,b)=>b.v-a.v);
      sorted.forEach(p=>{const [x,y]=v.P(p.at);const r=R(p);const c=o.byGroup||o.layer==='drill'?col(p.g+1):col(1);
        const rows=[[fmt(p.v,'$'),'Sales',o.byGroup||o.layer==='drill'?p.g+1:1]];if(p.ly)rows.push([fmtS((p.v/p.ly-1)*100,'%'),'vs last year','muted']);if(p.d)rows.push(['Click to drill into cities','','muted']);
        lay+=`<circle class="bub" data-i="${p.i}"${p.d?` data-d="${p.i}"`:''} cx="${n1(x)}" cy="${n1(y)}" r="${n1(r)}" style="fill:${c}" data-t="${tipA(p.n,rows)}"/>`;
        if(o.layer==='drill'&&(!(st.path||[]).length||r>9)&&o.labels!==false)lay+=`<text x="${n1(x)}" y="${n1(y-r-4)}" text-anchor="middle" class="lb">${esc(p.n)}</text>`;});
      if(o.byGroup)lay+=overlayLegend(REG4.map((n,k)=>({n,c:k+1})),6,6,fs);
      else if(o.layer!=='drill'&&W>=300)lay+=bubbleLegend(8,H-rmax*2-10,fs,vmax,rmax);}
    return svgWrap(W,H,fs,`<defs>${defs}</defs>`+s+`<g class="layers gm">${lay}</g>`,'data-map="w"','map'+(o.style?' ms-'+o.style:''));
  },
  bbox:worldBBox
};

/* ---- US map ---- */
const usState=a=>GEO.us.states.find(s=>s.a===a);
const REGS=Object.keys(USREG);
function usRegionBBox(r){const ss=GEO.us.states.filter(s=>US[s.a].r===r&&s.a!=='AK'&&s.a!=='HI');return [Math.min(...ss.map(s=>s.b[0])),Math.min(...ss.map(s=>s.b[1])),Math.max(...ss.map(s=>s.b[2])),Math.max(...ss.map(s=>s.b[3]))];}
function seqStep(v,mn,mx,steps){const t=(v-mn)/((mx-mn)||1);return Math.max(1,Math.min(steps,1+Math.floor(t*steps*.999)));}
function divColor(g){const t=Math.min(1,Math.abs(g)/14);const pct=Math.round(18+t*82);return `color-mix(in oklab, var(${g>=0?'--dpos':'--dneg'}) ${pct}%, var(--dmid))`;}
const TERR={Pacific:'WA OR CA AK HI NV',Mountain:'ID MT WY UT CO AZ NM',Central:'ND SD NE KS OK TX MN IA MO AR LA',Lakes:'WI IL MI IN OH KY',Southeast:'TN MS AL GA FL SC NC VA WV',Northeast:'PA NY NJ DE MD DC CT RI MA VT NH ME'};
const TERRI={};Object.entries(TERR).forEach(([k,v],i)=>v.split(' ').forEach(a=>{TERRI[a]=i;}));
E.usmap={
  draw(o,st,W,H){
    const fs=FS(W),G=GEO.us,v=mapView(G,W,H,st,o);
    const vals=G.states.map(s=>US[s.a].s);const mn=Math.min(...vals),mx=Math.max(...vals);
    const path=st.path||[];const drillR=o.fill==='drill'&&path.length?REGS[path[0]]:null;
    let sp='',lay='',defs='',leg='';
    G.states.forEach((s,i)=>{const d=US[s.a];let fill='var(--land)',extra='',rows=[[fmt(d.s,'$'),'Sales',1],[fmtS(d.g,'%'),'YoY growth','muted']];
      if(o.fill==='seq')fill=`var(--s${seqStep(Math.log(d.s),Math.log(mn),Math.log(mx),7)})`;
      else if(o.fill==='div')fill=divColor(d.g);
      else if(o.fill==='rules'){fill=d.g<0?'var(--crit)':d.g<6?'var(--warn)':'var(--good)';}
      else if(o.fill==='region'){fill=col(REGS.indexOf(d.r)+1);rows.push([d.r,'Region','muted']);}
      else if(o.fill==='ref'){fill=col(TERRI[s.a]+1);rows=[[Object.keys(TERR)[TERRI[s.a]],'Territory',TERRI[s.a]+1],[fmt(d.s,'$'),'Sales','muted']];}
      else if(o.fill==='drill'){if(!drillR){fill=col(REGS.indexOf(d.r)+1);extra=` data-d="${REGS.indexOf(d.r)}"`;rows=[[fmt(sumA(G.states.filter(x=>US[x.a].r===d.r).map(x=>US[x.a].s)),'$'),d.r+' sales',REGS.indexOf(d.r)+1],['Click to drill into states','','muted']];}
        else if(d.r===drillR){const rv=G.states.filter(x=>US[x.a].r===drillR).map(x=>US[x.a].s);fill=`var(--s${seqStep(d.s,Math.min(...rv),Math.max(...rv),6)+1})`;}
        else fill='var(--land)';}
      const hl=o.fill==='drill'&&!drillR?` data-i="${REGS.indexOf(d.r)}"`:` data-i="${i}"`;
      sp+=`<path class="st" d="${s.d}"${hl}${extra} style="fill:${fill}" data-t="${tipA(s.n,rows)}"/>`;});
    const base=`<rect class="water" width="${W}" height="${H}"/><g class="landg" transform="${v.tf}">${sp}</g>`;
    if(drillR){G.states.filter(s=>US[s.a].r===drillR).forEach(s=>{const [x,y]=v.P(s.c);if(s.b[2]-s.b[0]>18)lay+=`<text x="${n1(x)}" y="${n1(y+fs*.36)}" text-anchor="middle" class="mlab">${s.a}</text>`;});}
    if(o.fill==='ref'){Object.keys(TERR).forEach((t,i)=>{const ss=TERR[t].split(' ').filter(a=>a!=='AK'&&a!=='HI').map(usState);const cx=sumA(ss.map(s=>s.c[0]))/ss.length,cy=sumA(ss.map(s=>s.c[1]))/ss.length;const [x,y]=v.P([cx,cy]);lay+=`<text x="${n1(x)}" y="${n1(y)}" text-anchor="middle" class="mlab big">${t}</text>`;});}
    const cities=usPoints();const cmx=Math.max(...cities.map(c=>c.v));const rmax=W>=560?26:15;
    if(o.layer==='bubble')cities.slice().sort((a,b)=>b.v-a.v).forEach(c=>{const [x,y]=v.P(c.at);lay+=`<circle class="bub" data-i="${c.i}" cx="${n1(x)}" cy="${n1(y)}" r="${n1(Math.max(3,Math.sqrt(c.v/cmx)*rmax))}" style="fill:var(--c1)" data-t="${tipA(c.n,[[fmt(c.v,'$'),'Sales',1]])}"/>`;});
    if(o.layer==='3d'){const ord=cities.slice().sort((a,b)=>a.at[1]-b.at[1]);const hmax=H*.42,w=W>=560?10:6;
      ord.forEach(c=>{const [x,y]=v.P(c.at);const h=c.v/cmx*hmax;const d=w*.55;const fill=`var(--s${seqStep(c.v,0,cmx,4)+3})`;
        lay+=`<g class="col3" data-i="${c.i}" data-t="${tipA(c.n,[[fmt(c.v,'$'),'Sales',1]])}"><ellipse cx="${n1(x+d/2)}" cy="${n1(y)}" rx="${n1(w*.9)}" ry="${n1(w*.32)}" class="shadow"/><path d="M${n1(x-w/2)},${n1(y)}V${n1(y-h)}H${n1(x+w/2)}V${n1(y)}Z" style="fill:${fill}"/><path d="M${n1(x+w/2)},${n1(y)}V${n1(y-h)}L${n1(x+w/2+d)},${n1(y-h-d*.6)}V${n1(y-d*.6)}Z" style="fill:${fill};filter:brightness(.72)"/><path d="M${n1(x-w/2)},${n1(y-h)}L${n1(x-w/2+d)},${n1(y-h-d*.6)}H${n1(x+w/2+d)}L${n1(x+w/2)},${n1(y-h)}Z" style="fill:${fill};filter:brightness(1.25)"/></g>`;});}
    if(o.layer==='heat'){const id='hg'+(++UID);defs+=heatDefs(id);cities.forEach(c=>{const [x,y]=v.P(c.at);lay+=`<circle cx="${n1(x)}" cy="${n1(y)}" r="${n1((10+Math.sqrt(c.v/cmx)*rmax*1.6)*Math.sqrt(v.k))}" fill="url(#${id})" class="heat"/>`;});
      cities.forEach(c=>{const [x,y]=v.P(c.at);lay+=`<circle class="hit" data-i="${c.i}" cx="${n1(x)}" cy="${n1(y)}" r="10" data-t="${tipA(c.n,[[fmt(c.v,'$'),'Sales','heat3']])}"/>`;});}
    if(o.layer==='cluster'){const cell=W>=560?80:52;const cl=new Map();cities.forEach(c=>{const [x,y]=v.P(c.at);const key=Math.floor(x/cell)+','+Math.floor(y/cell);if(!cl.has(key))cl.set(key,[]);cl.get(key).push({...c,x,y});});
      cl.forEach(arr=>{const x=sumA(arr.map(a=>a.x))/arr.length,y=sumA(arr.map(a=>a.y))/arr.length;if(arr.length===1){lay+=`<circle class="bub" cx="${n1(x)}" cy="${n1(y)}" r="5" style="fill:var(--c2)" data-t="${tipA(arr[0].n,[[fmt(arr[0].v,'$'),'Sales',2]])}"/>`;}
        else{const r=9+Math.sqrt(arr.length)*4;lay+=`<g class="clu" data-z="${n1(x)},${n1(y)}" data-t="${tipA(arr.length+' stores',[[fmt(sumA(arr.map(a=>a.v)),'$'),'Sales',2],['Click to zoom in','','muted']])}"><circle cx="${n1(x)}" cy="${n1(y)}" r="${n1(r+5)}" class="clu-h c2"/><circle cx="${n1(x)}" cy="${n1(y)}" r="${n1(r)}" style="fill:var(--c2)"/><text x="${n1(x)}" y="${n1(y+fs*.36)}" text-anchor="middle" class="li">${arr.length}</text></g>`;}});}
    if(o.layer==='drive'){const [cx,cy]=v.P(GEO.us.cities['Chicago']);const rr=[46,30,16].map(r=>r*v.k*(W/360));
      rr.forEach((r,k)=>{let d='';for(let a=0;a<=64;a++){const t=a/64*Math.PI*2;const q=r*(1+.16*Math.sin(3*t+k)+.09*Math.sin(5*t+1.7)+.05*Math.cos(7*t));d+=(a?'L':'M')+n1(cx+q*Math.cos(t))+','+n1(cy+q*Math.sin(t)*.92);}
        lay+=`<path class="drive" d="${d}Z" style="fill-opacity:${[.16,.24,.36][k]}" data-t="${tipA(['30','20','10'][k]+'-minute drive time',[[fmt([1.9e6,1.1e6,4.6e5][k],''),'Population reached','c2']])}"/>`;});
      lay+=`<circle cx="${n1(cx)}" cy="${n1(cy)}" r="4.5" class="hub"/><text x="${n1(cx+7)}" y="${n1(cy-7)}" class="lb">Chicago store</text>`;}
    if(o.layer==='info'){const cw=W>=560?190:118,ch=W>=560?110:70;const stats=[['Population','9.4M'],['Median income','$78.2K'],['Avg household','2.6']];
      lay+=`<g class="info"><rect x="8" y="8" width="${cw}" height="${ch}" rx="8"/><text x="18" y="${8+fs+8}" class="lb">Chicago metro</text>${stats.map((st_,k)=>`<text x="18" y="${n1(8+fs*2+16+k*(fs+6))}" class="tk">${st_[0]}</text><text x="${cw-2}" y="${n1(8+fs*2+16+k*(fs+6))}" text-anchor="end" class="lb">${st_[1]}</text>`).join('')}</g>`;
      const [cx,cy]=v.P(GEO.us.cities['Chicago']);lay+=`<circle cx="${n1(cx)}" cy="${n1(cy)}" r="18" class="infohalo"/><circle cx="${n1(cx)}" cy="${n1(cy)}" r="4.5" class="hub"/>`;}
    if(o.fill==='seq'||o.fill==='div'){const lx=10,ly=H-(fs+18),lw=W>=560?150:92;const id='lgg'+(++UID);
      defs+=o.fill==='seq'?`<linearGradient id="${id}">${[1,2,3,4,5,6,7].map((k,j)=>`<stop offset="${(j/6).toFixed(2)}" style="stop-color:var(--s${k})"/>`).join('')}</linearGradient>`:`<linearGradient id="${id}"><stop offset="0" style="stop-color:var(--dneg)"/><stop offset=".5" style="stop-color:var(--dmid)"/><stop offset="1" style="stop-color:var(--dpos)"/></linearGradient>`;
      leg=`<rect x="${lx}" y="${ly}" width="${lw}" height="8" rx="4" fill="url(#${id})"/><text x="${lx}" y="${n1(ly+fs+12)}" class="tk">${o.fill==='seq'?fmt(mn,'$'):'−14%'}</text><text x="${lx+lw}" y="${n1(ly+fs+12)}" text-anchor="end" class="tk">${o.fill==='seq'?fmt(mx,'$'):'+14%'}</text>`;}
    if(o.fill==='rules')leg=overlayLegend([{n:'Declining (< 0%)',c:'crit'},{n:'Flat (0–6%)',c:'warn'},{n:'Growing (> 6%)',c:'good'}],6,H-3*(fs+6)-14,fs);
    if(o.fill==='region'||(o.fill==='drill'&&!drillR))leg=overlayLegend(REGS.map((n,k)=>({n,c:k+1})),6,H-4*(fs+6)-14,fs);
    return svgWrap(W,H,fs,`<defs>${defs}</defs>`+base+`<g class="layers gm">${lay}</g>`+leg,'data-map="us"','map'+(o.style?' ms-'+o.style:''));
  },
  bbox(o,st){const p=st.path||[];return p.length?usRegionBBox(REGS[p[0]]):null;}
};

/* ---- Shape map: hex tiles (custom TopoJSON style) ---- */
E.hexmap={draw(o,st,W,H){
  const fs=FS(W);const rows=8,colsN=12;const r=Math.min(W/(colsN*1.75+1),H/(rows*1.55+.6));const hw=Math.sqrt(3)*r;
  const ox=(W-(colsN*hw+hw/2))/2,oy=(H-(rows*1.5*r+r*.5))/2+r;
  const vals=Object.keys(HEX).map(a=>o.metric==='g'?US[a].g:US[a].s);const mn=Math.min(...vals),mx=Math.max(...vals);
  let s='',lab='';
  Object.entries(HEX).forEach(([a,[rw,cl]],i)=>{const cx=ox+cl*hw+(rw%2?hw/2:0)+hw/2,cy=oy+rw*1.5*r;let d='';for(let k=0;k<6;k++){const t=Math.PI/180*(60*k-30);d+=(k?'L':'M')+n1(cx+(r-1)*Math.cos(t))+','+n1(cy+(r-1)*Math.sin(t));}
    const d0=US[a];const fill=o.metric==='g'?divColor(d0.g):`var(--s${seqStep(Math.log(d0.s),Math.log(mn),Math.log(mx),6)+1})`;
    const st_=GEO.us.states.find(x=>x.a===a);
    s+=`<path class="m hx" data-i="${i}" d="${d}Z" style="fill:${fill}" data-t="${tipA(st_?st_.n:a,[[o.metric==='g'?fmtS(d0.g,'%'):fmt(d0.s,'$'),o.metric==='g'?'YoY growth':'Sales',o.metric==='g'?(d0.g>=0?'dpos':'dneg'):'s5']])}"/>`;
    const step=o.metric==='g'?Math.abs(d0.g)>8:seqStep(Math.log(d0.s),Math.log(mn),Math.log(mx),6)>=4;
    lab+=`<text x="${n1(cx)}" y="${n1(cy+fs*.36)}" text-anchor="middle" class="${step?'li':'hxl'}" font-size="${n1(Math.min(fs,r*.62))}">${a}</text>`;});
  return svgWrap(W,H,fs,`<g class="gm">${s}</g>`+lab);
}};
/* ---- Shape map: custom floor plan ---- */
E.floor={draw(o,st,W,H){
  const fs=FS(W);const sx=W/100,sy=H/62;
  const Z=[['Entrance',[[0,48],[22,48],[22,62],[0,62]],310],['Road bikes',[[0,0],[34,0],[34,28],[0,28]],1240],['Mountain bikes',[[34,0],[66,0],[66,28],[34,28]],1080],['Service bay',[[66,0],[100,0],[100,34],[66,34]],620],
    ['Apparel',[[0,28],[30,28],[30,48],[0,48]],880],['Accessories',[[30,28],[66,28],[66,46],[30,46]],1420],['E-bike studio',[[66,34],[100,34],[100,62],[66,62]],1690],['Checkout',[[22,46],[66,46],[66,62],[22,62]],540]];
  const mx=Math.max(...Z.map(z=>z[2])),mn=Math.min(...Z.map(z=>z[2]));let s='',lab='';
  Z.forEach((z,i)=>{const d=z[1].map((p,k)=>(k?'L':'M')+n1(p[0]*sx)+','+n1(p[1]*sy)).join('')+'Z';const stp=seqStep(z[2],mn,mx,5)+2;
    s+=`<path class="m zone" data-i="${i}" d="${d}" style="fill:var(--s${stp})" data-t="${tipA(z[0],[[fmt(z[2],'$'),'Sales per m²','s'+stp]])}"/>`;
    const xs=z[1].map(p=>p[0]),ys=z[1].map(p=>p[1]);const cx=(Math.min(...xs)+Math.max(...xs))/2*sx,cy=(Math.min(...ys)+Math.max(...ys))/2*sy;
    lab+=`<text x="${n1(cx)}" y="${n1(cy)}" text-anchor="middle" class="${stp>=4?'li':'lid'}">${esc(z[0])}</text><text x="${n1(cx)}" y="${n1(cy+fs+2)}" text-anchor="middle" class="${stp>=4?'li':'lid'}" font-weight="500">${fmt(z[2],'$')}/m²</text>`;});
  return svgWrap(W,H,fs,`<g class="gm">${s}</g>`+lab+`<path class="door" d="M${n1(6*sx)},${n1(62*sy)}h${n1(10*sx)}"/>`);
}};
