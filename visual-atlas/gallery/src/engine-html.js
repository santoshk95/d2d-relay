/* ============================================================
   HTML-based visuals (cards, KPI, tables, slicers, AI, embeds)
   Interactive pieces carry data-act="verb:arg"; E[k].act()
   updates the state and the app re-renders the visual.
   ============================================================ */
const TYS=sumA(TY),LYS=sumA(LY),PRS=sumA(PROF),PRLS=sumA(yearMonths(2024).map(m=>m.v[1])),ORD=sumA(UNITS),ORDL=sumA(yearMonths(2024).map(m=>m.v[2]));
const pctCh=(a,b)=>(a/b-1)*100;
function spark(vals,opt){
  opt=opt||{};const w=opt.w||120,h=opt.h||34,p=3;const mn=Math.min(...vals),mx=Math.max(...vals);
  const X=i=>p+i/(vals.length-1)*(w-p*2),Y=v=>h-p-(v-mn)/((mx-mn)||1)*(h-p*2);
  const pts=vals.map((v,i)=>[X(i),Y(v)]);const c=opt.c?col(opt.c):'var(--c1)';
  const last=pts[pts.length-1];
  return `<svg class="spk" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true">${opt.area!==false?`<path d="${linePath(pts)}L${n1(last[0])},${h}L${p},${h}Z" style="fill:${c};fill-opacity:.12"/>`:''}<path d="${linePath(pts)}" style="stroke:${c}" class="spl" vector-effect="non-scaling-stroke"/>${opt.dot!==false?`<circle cx="${n1(last[0])}" cy="${n1(last[1])}" r="2.6" style="fill:${c}" class="spd"/>`:''}</svg>`;
}
const arrow=(v,inv)=>{const good=inv?v<0:v>0;return `<b class="${good?'up':'down'}"><i aria-hidden="true">${v>0?'▲':'▼'}</i> ${fmt(Math.abs(v),'%')}</b>`;};
const ICON={
  bike:'<circle cx="6" cy="15" r="4.2"/><circle cx="18" cy="15" r="4.2"/><path d="M6 15l4-7h6l2 7M10 8l3 7h5M9 6h3"/>',
  gear:'<circle cx="12" cy="12" r="3.2"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1"/>',
  shirt:'<path d="M8 4l4 2 4-2 4 3-2 4-2-1v10H8V10l-2 1-2-4z"/>',
  helmet:'<path d="M4 15a8 8 0 0 1 16 0z"/><path d="M4 15h16M9 9l2 6M14 8l1 7"/>',
  globe:'<circle cx="12" cy="12" r="8"/><path d="M4 12h16M12 4c3 3 3 13 0 16M12 4c-3 3-3 13 0 16"/>',
  cart:'<path d="M3 5h3l2 10h10l2-7H7"/><circle cx="9" cy="19" r="1.4"/><circle cx="17" cy="19" r="1.4"/>',
  store:'<path d="M4 9l2-5h12l2 5M4 9h16v11H4zM9 20v-6h6v6"/>',
  handshake:'<path d="M3 12l4-4 4 2 3-2 4 1 3 3-6 5-3-2-3 2z"/>'
};
const ic=(k,cls)=>`<svg class="${cls||'ico'}" viewBox="0 0 24 24" aria-hidden="true">${ICON[k]}</svg>`;
const catIcon=c=>({Bikes:'bike',Components:'gear',Clothing:'shirt',Accessories:'helmet'}[c]||'gear');
const H_=(cls,inner,extra)=>`<div class="hv ${cls}"${extra||''}>${inner}</div>`;

/* ---------------- Card (GA since Nov 2025) ---------------- */
const KCARDS=[
  {l:'Sales',v:TYS,u:'$',ly:LYS,tg:TYS*.97,ic:'$',tr:TY},
  {l:'Profit',v:PRS,u:'$',ly:PRLS,tg:PRS*1.06,ic:'%',tr:PROF},
  {l:'Orders',v:ORD,u:'',ly:ORDL,tg:ORD*.99,ic:'#',tr:UNITS},
  {l:'Return rate',v:2.8,u:'%',ly:3.1,tg:3,ic:'↺',inv:true,tr:[3.4,3.3,3.2,3.3,3.1,3,3.1,2.9,2.9,2.8,2.8,2.8]}
];
function cardHtml(c,o,i){
  const d=pctCh(c.v,c.ly);const below=c.inv?c.v>c.tg:c.v<c.tg;
  const refs=o.refs?`<div class="cd-refs">${o.refs.includes('ly')?`<div class="cd-ref"><span>vs last year</span>${arrow(d,c.inv)}</div>`:''}${o.refs.includes('tg')?`<div class="cd-ref"><span>Target ${fmt(c.tg,c.u)}</span><b class="${below?'down':'up'}">${(c.v/c.tg*100).toFixed(0)}%</b></div>`:''}</div>`:'';
  const acc=o.cf&&below?' cd-alert':'';
  return `<div class="cd${acc}${o.horiz?' cd-h':''}" data-i="${i}" data-t="${tipA(c.l,[[fmt(c.v,c.u),'This year',1],[fmt(c.ly,c.u),'Last year','muted'],[fmt(c.tg,c.u),'Target','muted']])}">
    ${o.img?`<div class="cd-img">${spark(c.tr,{c:below&&o.cf?'crit':1})}</div>`:''}
    <div class="cd-call">${o.icons?`<span class="cd-ic">${c.ic}</span>`:''}<div class="cd-cv"><div class="cd-v">${fmt(c.v,c.u)}</div><div class="cd-l">${c.l}</div></div></div>${refs}</div>`;
}
E.card={draw(o,st,W,H){
  if(o.legacy)return H_('lc-wrap',`<div class="lc" data-i="0" data-t="${tipA('Sales',[[fmt(TYS,'$'),'Sales',1]])}"><div class="lc-v">${fmt(TYS,'$')}</div><div class="lc-l">Sales</div></div>`);
  if(o.cats){const cats=[{h:'Online',f:.42},{h:'Retail',f:.39},{h:'Partner',f:.19}];
    return H_('cd-cats',cats.map((c,ci)=>`<div class="cd-cat" data-i="${ci}"><div class="cd-ch">${ic(['cart','store','handshake'][ci],'ico sm')} ${c.h}</div><div class="cd-grid" style="--cols:2">${KCARDS.slice(0,2).map((k,i)=>cardHtml({...k,v:k.v*c.f,ly:k.ly*c.f*(1+(ci-1)*.04),tg:k.tg*c.f},o,ci*10+i)).join('')}</div></div>`).join(''));}
  const cs=KCARDS.slice(0,o.n||1);
  return H_('cd-grid'+(o.n===1?' one':''),cs.map((c,i)=>cardHtml(c,o,i)).join(''),` style="--cols:${o.cols||cs.length}"`);
}};
/* ---------------- Multi-row card (legacy) ---------------- */
E.mrow={draw(o){
  const rows=o.measures?[{t:null,f:[[fmt(TYS,'$'),'Sales'],[fmt(PRS,'$'),'Profit'],[fmt(ORD,''),'Orders'],[(PRS/TYS*100).toFixed(1)+'%','Margin']]}]
    :HG.root.c.map((r,i)=>{const a=agg(r);return {t:r.n,f:[[fmt(a[0],'$'),'Sales'],[fmt(a[1],''),'Customers'],[fmtS(pctCh(a[0],a[2]),'%'),'vs LY']]};});
  return H_('mr'+(o.accent?' mr-acc':'')+(o.two?' mr-two':''),rows.map((r,i)=>`<div class="mr-row" data-i="${i}">${r.t?`<div class="mr-t">${r.t}</div>`:''}<div class="mr-fs">${r.f.map(f=>`<div class="mr-f"><b>${f[0]}</b><span>${f[1]}</span></div>`).join('')}</div></div>`).join(''));
}};
/* ---------------- KPI ---------------- */
function kpiHtml(k,o){
  const good=k.inv?k.v<=k.goal:k.v>=k.goal;const dist=(k.v/k.goal-1)*100;
  const distTxt=o.abs?fmtS(k.v-k.goal,k.u):fmtS(dist,'%');
  const tr=k.tr;const w=200,h=60;const mn=Math.min(...tr),mx=Math.max(...tr);const X=i=>i/(tr.length-1)*w,Y=v=>h-4-(v-mn)/((mx-mn)||1)*(h-12);const pts=tr.map((v,i)=>[X(i),Y(v)]);
  const svg=o.notrend?'':`<svg class="kp-tr" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true"><path d="${linePath(pts)}L${w},${h}L0,${h}Z" class="kp-a"/><path d="${linePath(pts)}" class="kp-l" vector-effect="non-scaling-stroke"/></svg>`;
  return `<div class="kp ${good?'good':'bad'}" data-t="${tipA(k.l,[[fmt(k.v,k.u),'Indicator',good?'good':'crit'],[fmt(k.goal,k.u),'Goal','muted'],[distTxt,'Distance to goal','muted']])}"><div class="kp-h">${k.l}</div><div class="kp-v">${fmt(k.v,k.u)}</div><div class="kp-s"><span class="kp-ic" aria-hidden="true">${good?'✓':'!'}</span>${good?'On track':'Behind goal'}</div><div class="kp-g">Goal: ${fmt(k.goal,k.u)} <b>(${distTxt})</b>${o.date?` <span class="kp-d">· Dec 2025</span>`:''}</div>${svg}</div>`;
}
const KPIS=[{l:'Sales',v:TYS,goal:TYS*.95,u:'$',tr:TY},{l:'Profit',v:PRS,goal:PRS*1.08,u:'$',tr:PROF},{l:'Return rate',v:2.8,goal:3,u:'%',inv:true,tr:[3.4,3.3,3.2,3.3,3.1,3,3.1,2.9,2.9,2.8,2.8,2.8]},{l:'Avg delivery days',v:4.6,goal:4,u:'',inv:true,tr:[3.9,4,4.1,4.2,4.4,4.3,4.5,4.6,4.4,4.5,4.7,4.6]}];
E.kpi={draw(o){const ks=o.row?KPIS:[KPIS[o.i||0]];return H_('kp-row'+(o.row?' multi':''),ks.map(k=>kpiHtml(k,o)).join(''),` style="--cols:${ks.length}"`);}};
/* ---------------- Gauge ---------------- */
function gaugeSvg(g,o,W,H,i){
  const fs=FS(W);const cx=W/2,cy=H*(o.compact?.72:.7),R=Math.min(W*.4,H*.58),th=R*.26;
  const mn=g.min??0,mx=g.max??1;const t=v=>Math.PI+Math.max(0,Math.min(1,(v-mn)/(mx-mn)))*Math.PI;
  const arc=(a0,a1,r1,r2)=>{const p=(r,a)=>[cx+r*Math.cos(a),cy+r*Math.sin(a)];const [x0,y0]=p(r1,a0),[x1,y1]=p(r1,a1),[x2,y2]=p(r2,a1),[x3,y3]=p(r2,a0);const big=a1-a0>Math.PI?1:0;return `M${n1(x0)},${n1(y0)}A${n1(r1)},${n1(r1)} 0 ${big},1 ${n1(x1)},${n1(y1)}L${n1(x2)},${n1(y2)}A${n1(r2)},${n1(r2)} 0 ${big},0 ${n1(x3)},${n1(y3)}Z`;};
  const pct=g.v/(g.tgt||mx);let fill=col(g.c||1);if(o.rule){fill=pct>=.95?'var(--good)':pct>=.8?'var(--warn)':'var(--crit)';}
  let s=`<path class="gtrack" d="${arc(Math.PI,Math.PI*2,R,R-th)}"/><path class="m gfill" data-i="${i||0}" d="${arc(Math.PI,t(g.v),R,R-th)}" style="fill:${fill}"/>`;
  if(g.tgt!=null&&o.target!==false){const a=t(g.tgt);s+=`<line class="gtgt" x1="${n1(cx+(R-th-4)*Math.cos(a))}" y1="${n1(cy+(R-th-4)*Math.sin(a))}" x2="${n1(cx+(R+4)*Math.cos(a))}" y2="${n1(cy+(R+4)*Math.sin(a))}"/><text x="${n1(cx+(R+8)*Math.cos(a))}" y="${n1(cy+(R+8)*Math.sin(a)-2)}" text-anchor="${Math.cos(a)>.2?'start':Math.cos(a)<-.2?'end':'middle'}" class="tk">${o.pct?Math.round(g.tgt*100)+'%':fmt(g.tgt,g.u)}</text>`;}
  if(o.minmax!==false)s+=`<text x="${n1(cx-R+th/2)}" y="${n1(cy+fs+5)}" text-anchor="middle" class="tk">${o.pct?Math.round(mn*100)+'%':fmt(mn,g.u)}</text><text x="${n1(cx+R-th/2)}" y="${n1(cy+fs+5)}" text-anchor="middle" class="tk">${o.pct?Math.round(mx*100)+'%':fmt(mx,g.u)}</text>`;
  if(o.callout!==false)s+=`<text x="${n1(cx)}" y="${n1(cy-R*.12)}" text-anchor="middle" class="gv" font-size="${n1(Math.min(R*.42,fs*3.4))}">${o.pct?(g.v*100).toFixed(1)+'%':fmt(g.v,g.u)}</text>`;
  s+=`<text x="${n1(cx)}" y="${n1(cy+(o.callout!==false?fs*.3:-R*.2))}" text-anchor="middle" class="tk">${esc(g.l)}</text>`;
  return svgWrap(W,H,fs,s,`data-t="${tipA(g.l,[[o.pct?(g.v*100).toFixed(1)+'%':fmt(g.v,g.u),'Value',1],[g.tgt!=null?(o.pct?Math.round(g.tgt*100)+'%':fmt(g.tgt,g.u)):'–','Target','muted']])}"`);
}
E.gauge={draw(o,st,W,H){
  if(o.strip){const gs=[{l:'Americas',v:.92,tgt:.9},{l:'Europe',v:.81,tgt:.9},{l:'Asia Pacific',v:.97,tgt:.9},{l:'MEA',v:.68,tgt:.9}];return H_('g-strip',gs.map((g,i)=>`<div>${gaugeSvg({...g,min:0,max:1.2},{...o,pct:true,compact:true},W/2,H/2,i)}</div>`).join(''));}
  return gaugeSvg(o.g,o,W,H,0);
}};
/* ---------------- Goals (metrics / scorecard) ---------------- */
const GOALS=[{n:'Grow revenue to $10M',o:'AK',s:'On track',v:fmt(TYS,'$'),t:'$10M',p:TYS/1e7,tr:TY},{n:'Gross margin ≥ 43%',o:'MR',s:'At risk',v:'41.8%',t:'43%',p:.972,tr:[44,43.6,43,42.8,42.5,42.1,42.3,42,41.9,41.7,41.9,41.8]},{n:'NPS above 45',o:'JS',s:'Behind',v:'38',t:'45',p:.84,tr:[41,40,40,39,38,37,38,38,37,38,38,38]},{n:'Launch store app',o:'DL',s:'Completed',v:'Done',t:'Q3',p:1,tr:[0,1,2,3,5,6,7,8,9,10,10,10]},{n:'Cut returns to 2.5%',o:'TW',s:'On track',v:'2.8%',t:'2.5%',p:.89,tr:[3.4,3.3,3.2,3.3,3.1,3,3.1,2.9,2.9,2.8,2.8,2.8]}];
const GST={'On track':['good','✓'],'At risk':['warn','!'],'Behind':['crit','✕'],'Completed':['c1','★']};
const gPill=s=>`<span class="gp gp-${GST[s][0]}"><i aria-hidden="true">${GST[s][1]}</i>${s}</span>`;
E.goals={draw(o){
  if(o.single){const g=GOALS[0];return H_('go-one',`<div class="go-oh">${gPill(g.s)}<span class="go-own">${g.o}</span></div><div class="go-on">${g.n}</div><div class="go-ov">${g.v} <span>of ${g.t}</span></div><div class="go-bar"><i style="width:${Math.min(100,g.p*100)}%"></i></div>${spark(g.tr,{w:220,h:46})}`);}
  const rows=o.roll?[GOALS[0],{...GOALS[0],n:'Online revenue',sub:1,s:'On track',v:'$3.9M',t:'$4.2M',p:.93},{...GOALS[0],n:'Retail revenue',sub:1,s:'At risk',v:'$3.6M',t:'$4.1M',p:.88},{...GOALS[0],n:'Partner revenue',sub:1,s:'Completed',v:'$1.9M',t:'$1.7M',p:1},GOALS[1]]:GOALS;
  return H_('goal',`<div class="go-hd"><span>Goal</span><span>Status</span><span>Value</span><span>Progress</span></div>`+rows.map((g,i)=>`<div class="go-r${g.sub?' sub':''}" data-i="${i}"><div class="go-n"><span class="go-own">${g.o}</span><span>${g.n}</span></div><div>${gPill(g.s)}</div><div class="go-v">${g.v} <span>/ ${g.t}</span></div><div class="go-p"><div class="go-bar"><i style="width:${Math.min(100,g.p*100)}%"></i></div>${o.notes?'':spark(g.tr,{w:60,h:18,area:false})}</div>${o.notes&&i<3?`<div class="go-note">${['“Q4 promo lifted November; December pipeline is strong.”','“Freight costs squeezed margin; supplier renegotiation in progress.”','“Survey response rate fell; new post-delivery prompt ships next sprint.”'][i]}<span>Check-in · ${['Dec 2','Nov 28','Nov 21'][i]}</span></div>`:''}</div>`).join(''));
}};

/* ---------------- Table ---------------- */
E.table={
  draw(o,st){
    const sc=st.sc||o.sortBy||'s',sd=st.sd||'desc';
    let rows=TROWS.slice();rows.sort((a,b)=>(typeof a[sc]==='string'?a[sc].localeCompare(b[sc]):a[sc]-b[sc])*(sd==='asc'?1:-1));
    const mxS=Math.max(...rows.map(r=>r.s)),mnS=Math.min(...rows.map(r=>r.s));const tot=sumA(rows.map(r=>r.s));
    const cols=[['n','Product','t'],...(o.cat?[['cat','Category','t']]:[]),['s','Sales','$'],['u','Units',''],['m','Margin','%'],['y','YoY','%']];
    if(o.cf==='calc'||o.cf==='img'){for(const k of ['u','m'])cols.splice(cols.findIndex(c=>c[0]===k),1);}
    if(o.cf==='calc')cols.splice(cols.findIndex(c=>c[0]==='y'),1);
    if(o.cf==='spark')cols.push(['tr','Trend','spark']);
    if(o.cf==='calc')cols.push(['rt','Running total','calc'],['pt','% of total','calc']);
    if(o.cf==='img')cols.splice(1,0,['img','','img']),cols.push(['url','Link','url']);
    const th=cols.map(c=>{const sortable=['t','$','','%'].includes(c[2])&&c[0]!=='img';return `<th class="${c[2]==='t'?'tl':''}${sc===c[0]?' sorted':''}"${sortable?` data-act="sort:${c[0]}"`:''}>${c[2]==='calc'?'<span class="fx">fx</span>':''}${c[1]}${sc===c[0]?`<i aria-hidden="true">${sd==='asc'?'▲':'▼'}</i>`:''}</th>`;}).join('');
    let run=0;
    const tr=rows.map((r,i)=>{run+=r.s;return `<tr data-i="${i}" data-t="${tipA(r.n,[[fmt(r.s,'$'),'Sales',1],[r.m+'%','Margin','muted'],[fmtS(r.y,'%'),'YoY','muted']])}">`+cols.map(c=>{const k=c[0];const v=r[k];
      if(k==='n')return `<td class="tl">${o.cf==='img'?'':''}${esc(v)}</td>`;
      if(k==='cat')return `<td class="tl muted">${v}</td>`;
      if(k==='img')return `<td class="timg">${ic(catIcon(r.cat),'ico')}</td>`;
      if(k==='url')return `<td class="turl">example.com/p/${r.n.toLowerCase().replace(/\s+/g,'-')} <span aria-hidden="true">↗</span></td>`;
      if(k==='tr')return `<td class="tspk">${spark(v,{w:64,h:18,area:false})}</td>`;
      if(k==='rt')return `<td>${fmt(run,'$')}</td>`;
      if(k==='pt')return `<td>${(r.s/tot*100).toFixed(1)}%</td>`;
      if(k==='s'){const t=(v-mnS)/((mxS-mnS)||1);if(o.cf==='bg')return `<td style="background:color-mix(in oklab, var(--c1) ${Math.round(8+t*50)}%, transparent)">${fmt(v,'$')}</td>`;if(o.cf==='bars')return `<td class="tdb"><div class="db"><i style="width:${Math.round(v/mxS*100)}%"></i><span>${fmt(v,'$')}</span></div></td>`;return `<td>${fmt(v,'$')}</td>`;}
      if(k==='y'){if(o.cf==='icons'){const s=v>5?['good','▲']:v>=0?['warn','●']:['crit','▼'];return `<td><span class="tic tic-${s[0]}" aria-hidden="true">${s[1]}</span>${fmtS(v,'%')}</td>`;}if(o.cf==='font')return `<td class="${v<0?'fneg':v>8?'fpos':''}">${fmtS(v,'%')}</td>`;return `<td>${fmtS(v,'%')}</td>`;}
      if(k==='m')return `<td>${v.toFixed(1)}%</td>`;
      return `<td>${fmt(v,'')}</td>`;}).join('')+'</tr>';}).join('');
    const totRow=o.total===false?'':`<tr class="ttot">`+cols.map((c,ci)=>{const k=c[0];if(ci===0)return '<td class="tl">Total</td>';if(k==='s')return `<td>${fmt(tot,'$')}</td>`;if(k==='u')return `<td>${fmt(sumA(rows.map(r=>r.u)),'')}</td>`;if(k==='rt')return `<td>${fmt(tot,'$')}</td>`;if(k==='pt')return '<td>100%</td>';if(k==='m')return `<td>${(sumA(rows.map(r=>r.s*r.m))/tot).toFixed(1)}%</td>`;return '<td></td>';}).join('')+'</tr>';
    return H_('tbl-wrap',`<table class="tbl ${o.style||'std'}"><thead><tr>${th}</tr></thead><tbody>${tr}</tbody><tfoot>${totRow}</tfoot></table>`);
  },
  act(o,st,a,arg){if(a==='sort'){if(st.sc===arg||(!st.sc&&(o.sortBy||'s')===arg))st.sd=(st.sd||'desc')==='desc'?'asc':'desc';else{st.sc=arg;st.sd=arg==='n'||arg==='cat'?'asc':'desc';}return true;}}
};

/* ---------------- Matrix ---------------- */
E.matrix={
  draw(o,st){
    const open=st.open||o.open||[];const Q=QTR.map(q=>q+' 2025');
    const rowsMeta=[];
    const regs=st.path&&st.path.length?[MAT[st.path[0]]]:MAT;
    const allQ=MAT.flatMap(r=>r.c.flatMap(c=>c.q));const mx=Math.max(...allQ),mn=Math.min(...allQ);
    const cell=(v,isTot)=>{if(o.heat&&!isTot){const t=(v-mn)/((mx-mn)||1);return `<td style="background:color-mix(in oklab, var(--c1) ${Math.round(6+t*52)}%, transparent)">${fmt(v,'$')}</td>`;}return `<td>${fmt(v,'$')}</td>`;};
    const trendCell=q=>o.spark?`<td class="tspk">${spark(q,{w:56,h:16,area:false})}</td>`:'';
    const barCell=(t,max)=>o.bars?`<td class="tdb"><div class="db"><i style="width:${Math.round(t/max*100)}%"></i><span>${fmt(t,'$')}</span></div></td>`:`<td class="mtot">${fmt(t,'$')}</td>`;
    const regTot=r=>QTR.map((_,k)=>sumA(r.c.map(c=>c.q[k])));
    const grand=QTR.map((_,k)=>sumA(MAT.map(r=>sumA(r.c.map(c=>c.q[k])))));const gT=sumA(grand);
    const maxRow=Math.max(...MAT.map(r=>sumA(regTot(r))));
    let body='';
    if(o.vrows){
      MAT.forEach((r,ri)=>{const t=regTot(r);const p=t.map(v=>Math.round(v*(.17+ri*.012)));
        body+=`<tr class="mreg"><td class="tl" colspan="${Q.length+2}">${r.n}</td></tr><tr data-i="${ri}"><td class="tl ind">Sales</td>${t.map(v=>cell(v)).join('')}<td class="mtot">${fmt(sumA(t),'$')}</td></tr><tr data-i="${ri}"><td class="tl ind">Profit</td>${p.map(v=>cell(v)).join('')}<td class="mtot">${fmt(sumA(p),'$')}</td></tr>`;});
      return H_('tbl-wrap',`<table class="tbl mtx"><thead><tr><th class="tl">Region</th>${Q.map(q=>`<th>${q}</th>`).join('')}<th>Total</th></tr></thead><tbody>${body}</tbody></table>`);
    }
    if(st.flat){MAT.forEach(r=>r.c.forEach((c,ci)=>{body+=`<tr><td class="tl">${c.n}</td>${c.q.map(v=>cell(v)).join('')}${trendCell(c.q)}${barCell(sumA(c.q),maxRow)}</tr>`;}));}
    else regs.forEach(r=>{const ri=MAT.indexOf(r);const t=regTot(r);const isOpen=open.includes(ri)||(st.path&&st.path.length)||o.layout==='tabular';
      const btn=o.layout==='tabular'?'':`<button class="tog" data-act="tog:${ri}" aria-label="${isOpen?'Collapse':'Expand'} ${r.n}">${isOpen?'−':'+'}</button>`;
      if(o.layout==='tabular'){r.c.forEach((c,ci)=>{body+=`<tr data-i="${ri}"><td class="tl${ci?' rep':''}">${r.n}</td><td class="tl">${c.n}</td>${c.q.map(v=>cell(v)).join('')}${trendCell(c.q)}${barCell(sumA(c.q),maxRow)}</tr>`;});body+=`<tr class="msub"><td class="tl">${r.n} total</td><td></td>${t.map(v=>cell(v,1)).join('')}${o.spark?'<td></td>':''}<td class="mtot">${fmt(sumA(t),'$')}</td></tr>`;return;}
      body+=`<tr class="mreg" data-i="${ri}"><td class="tl">${btn}${r.n}</td>${t.map(v=>cell(v,1)).join('')}${trendCell(t)}${barCell(sumA(t),maxRow)}</tr>`;
      if(isOpen)r.c.forEach(c=>{body+=`<tr data-i="${ri}"><td class="tl ind">${c.n}</td>${c.q.map(v=>cell(v)).join('')}${trendCell(c.q)}${barCell(sumA(c.q),maxRow)}</tr>`;});});
    const head=`<tr>${o.layout==='tabular'?'<th class="tl">Region</th><th class="tl">Country</th>':`<th class="tl">${st.flat?'Country':st.path&&st.path.length?MAT[st.path[0]].n:'Region'}</th>`}${Q.map(q=>`<th>${q}</th>`).join('')}${o.spark?'<th>Trend</th>':''}<th>Total</th></tr>`;
    const foot=`<tr class="ttot"><td class="tl">Total</td>${o.layout==='tabular'?'<td></td>':''}${grand.map(v=>`<td>${fmt(v,'$')}</td>`).join('')}${o.spark?'<td></td>':''}<td>${fmt(gT,'$')}</td></tr>`;
    return H_('tbl-wrap',`<table class="tbl mtx"><thead>${head}</thead><tbody>${body}</tbody><tfoot>${foot}</tfoot></table>`);
  },
  act(o,st,a,arg){if(a==='tog'){const i=+arg;const open=(st.open||o.open||[]).slice();const k=open.indexOf(i);if(k>=0)open.splice(k,1);else open.push(i);st.open=open;return true;}}
};

/* ---------------- Slicer (classic) ---------------- */
const chk=on=>`<span class="ck${on?' on':''}" aria-hidden="true">${on?'✓':''}</span>`;
E.slicer={
  draw(o,st){
    const items=o.items||REG4;const sel=st.sel||o.sel||[];const m=o.mode;
    const head=`<div class="sl-h"><span>${o.field||'Region'}</span>${sel.length?`<button class="sl-clr" data-act="clr" aria-label="Clear selections">⌫</button>`:''}</div>`;
    if(m==='dropdown'){const lab=sel.length===0?'All':sel.length===1?items[sel[0]]:'Multiple selections';
      return H_('sl',head+`<button class="sl-dd${st.open?' open':''}" data-act="open"><span>${lab}</span><i aria-hidden="true">▾</i></button>`+(st.open?`<div class="sl-pop">${items.map((it,i)=>`<div class="sl-it" data-act="sel:${i}">${chk(sel.includes(i))}${it}</div>`).join('')}</div>`:''));}
    if(m==='tile')return H_('sl',head+`<div class="sl-tiles">${items.map((it,i)=>`<button class="sl-tile${sel.includes(i)?' on':''}" data-act="sel:${i}">${it}</button>`).join('')}</div>`);
    if(m==='between'||m==='date'){const r=st.r||o.r||[.2,.75];const mn=o.min,mx=o.max;const val=t=>m==='date'?fmtDate(mn+(mx-mn)*t):fmt(Math.round(mn+(mx-mn)*t),o.u);
      return H_('sl',head+`<div class="sl-rng"><div class="sl-in">${m==='date'?'<span class="cal" aria-hidden="true">▦</span>':''}${val(r[0])}</div><div class="sl-in">${m==='date'?'<span class="cal" aria-hidden="true">▦</span>':''}${val(r[1])}</div></div><div class="sl-track" data-act="rng"><i style="left:${r[0]*100}%;right:${100-r[1]*100}%"></i><b style="left:${r[0]*100}%"></b><b style="left:${r[1]*100}%"></b></div>`);}
    if(m==='relative'){const n=st.rn||3;return H_('sl',head+`<div class="sl-rel"><button class="sl-dd" data-act="rel"><span>Last</span><i aria-hidden="true">▾</i></button><button class="sl-dd num" data-act="relN"><span>${n}</span></button><button class="sl-dd" data-act="rel"><span>Months (Calendar)</span><i aria-hidden="true">▾</i></button></div><div class="sl-cap">${fmtDate(new Date(2026,10-n,1))} – Oct 31, 2026</div><div class="sl-hint">Rolls forward each time the report loads</div>`);}
    if(m==='hier'){const open=st.open||[1];
      return H_('sl',head+HD.root.c.map((y,yi)=>{const kids=y.c.map((q,qi)=>yi*10+qi);const on=kids.filter(k=>sel.includes(k)).length;const state=on===0?'':on===kids.length?' on':' part';
        return `<div class="sl-it" data-act="hy:${yi}"><button class="sl-ex" data-act="hx:${yi}" aria-label="Expand">${open.includes(yi)?'▾':'▸'}</button><span class="ck${state}" aria-hidden="true">${state===' on'?'✓':state?'–':''}</span>${y.n}</div>`+(open.includes(yi)?y.c.map((q,qi)=>`<div class="sl-it sub" data-act="sel:${yi*10+qi}">${chk(sel.includes(yi*10+qi))}${q.n}</div>`).join(''):'');}).join(''));}
    const search=o.search?`<div class="sl-search">${'<span aria-hidden="true">⌕</span>'}<span>${st.q||'Search'}</span></div>`:'';
    const all=o.all?`<div class="sl-it" data-act="all">${chk(sel.length===items.length)}<span>Select all</span></div>`:'';
    return H_('sl',head+search+all+items.map((it,i)=>`<div class="sl-it" data-act="sel:${i}">${m==='single'?`<span class="rd${sel.includes(i)?' on':''}" aria-hidden="true"></span>`:chk(sel.includes(i))}${it}</div>`).join(''));
  },
  act(o,st,a,arg,ev,el){
    const items=o.items||REG4;let sel=(st.sel||o.sel||[]).slice();
    if(a==='sel'){const i=+arg;if(o.mode==='single'){sel=sel.includes(i)?[]:[i];}else{const k=sel.indexOf(i);if(k>=0)sel.splice(k,1);else sel.push(i);}st.sel=sel;return true;}
    if(a==='all'){st.sel=sel.length===items.length?[]:items.map((_,i)=>i);return true;}
    if(a==='clr'){st.sel=[];return true;}
    if(a==='open'){st.open=!st.open;return true;}
    if(a==='relN'){st.rn=((st.rn||3)%12)+1;return true;}
    if(a==='hx'){const i=+arg;const op=(st.open||[1]).slice();const k=op.indexOf(i);if(k>=0)op.splice(k,1);else op.push(i);st.open=op;return true;}
    if(a==='hy'){const yi=+arg;const kids=[0,1,2,3].map(q=>yi*10+q);const allOn=kids.every(k=>sel.includes(k));sel=sel.filter(k=>!kids.includes(k));if(!allOn)sel.push(...kids);st.sel=sel;return true;}
    if(a==='rng'&&ev){const r=(st.r||o.r||[.2,.75]).slice();const box=el.getBoundingClientRect();const t=Math.max(0,Math.min(1,(ev.clientX-box.left)/box.width));if(Math.abs(t-r[0])<Math.abs(t-r[1]))r[0]=Math.min(t,r[1]-.05);else r[1]=Math.max(t,r[0]+.05);st.r=r;return true;}
  }
};
function fmtDate(d){const dt=new Date(d);return `${MON[dt.getMonth()]} ${dt.getDate()}, ${dt.getFullYear()}`;}

/* ---------------- Button slicer ---------------- */
E.bslicer={
  draw(o,st){
    const items=o.items;const sel=st.sel||o.sel||[];
    return H_('bs'+(o.vert?' vert':''),`<div class="bs-g" style="--cols:${o.cols||items.length}">`+items.map((it,i)=>{const cf=o.cf?(it.g>=0?' cf-good':' cf-crit'):'';
      return `<button class="bs-b${sel.includes(i)?' on':''}${cf}${o.hl!=null&&o.hl!==i&&o.hlMode?' dim':''}" data-act="sel:${i}">${it.ic?ic(it.ic,'ico bs-ic'):''}<span class="bs-txt"><span class="bs-n">${it.n}</span>${o.val?`<span class="bs-v">${it.v}</span>`:''}</span></button>`;}).join('')+'</div>');
  },
  act(o,st,a,arg){if(a==='sel'){const i=+arg;let sel=(st.sel||o.sel||[]).slice();if(o.single){sel=o.force?[i]:(sel[0]===i?[]:[i]);}else{const k=sel.indexOf(i);if(k>=0)sel.splice(k,1);else sel.push(i);}st.sel=sel;return true;}}
};
/* ---------------- List slicer (preview) ---------------- */
E.lslicer={
  draw(o,st){
    const sel=st.sel||o.sel||[];
    if(o.mode==='dropdown'){const names=sel.map(i=>REG4[i]);const show=names.slice(0,2);
      return H_('ls',`<div class="sl-h"><span>Region</span></div><div class="ls-dd${st.open?' open':''}" data-act="open">${show.map(n=>`<span class="pill-s">${n}<i data-act="rm:${REG4.indexOf(n)}" aria-label="Remove">✕</i></span>`).join('')}${names.length>2?`<span class="pill-c">+${names.length-2}</span>`:''}${!names.length?'<span class="ph">All</span>':''}<i class="car" aria-hidden="true">▾</i></div>`+(st.open?`<div class="sl-pop">${REG4.map((n,i)=>`<div class="sl-it" data-act="sel:${i}">${chk(sel.includes(i))}${n}</div>`).join('')}</div>`:''));}
    if(o.mode==='hier'||o.mode==='leaf'){const open=st.open||[0,1];
      return H_('ls',`<div class="sl-h"><span>Category › Subcategory</span></div>`+HP.root.c.map((c,ci)=>{const kids=c.c.map((s,si)=>ci*10+si);const on=kids.filter(k=>sel.includes(k)).length;
        return `<div class="ls-it par${o.mode==='leaf'?' nosel':''}" data-act="${o.mode==='leaf'?'hx':'hy'}:${ci}"><button class="sl-ex" data-act="hx:${ci}" aria-label="Expand">${open.includes(ci)?'▾':'▸'}</button>${o.mode==='leaf'?'':`<span class="ck${on===kids.length?' on':on?' part':''}" aria-hidden="true">${on===kids.length?'✓':on?'–':''}</span>`}<span>${c.n}</span><span class="ls-v">${fmt(agg(c)[0],'$')}</span></div>`+(open.includes(ci)?c.c.map((s,si)=>`<div class="ls-it sub" data-act="sel:${ci*10+si}">${chk(sel.includes(ci*10+si))}<span>${s.n}</span><span class="ls-v">${fmt(agg(s)[0],'$')}</span></div>`).join(''):'');}).join(''));}
    const items=HP.root.c.map(c=>({n:c.n,v:agg(c)[0],p:agg(c)[1]/agg(c)[0]}));
    const search=o.mode==='search'?`<div class="sl-search"><span aria-hidden="true">⌕</span><span class="typed">${st.q||'ac'}</span></div>`:'';
    const list=o.mode==='search'?SUBS.filter(s=>s.n.toLowerCase().includes((st.q||'ac').toLowerCase())).map(s=>({n:s.n,v:s.v[0],cat:s.cat,p:s.v[1]/s.v[0]})):items;
    return H_('ls',`<div class="sl-h"><span>${o.mode==='search'?'Subcategory':'Category'}</span></div>`+search+list.map((it,i)=>{const cf=o.mode==='cf'?(it.p>.25?' cf-good':it.p>.15?'':' cf-crit'):'';
      return `<div class="ls-it${cf}${sel.includes(i)?' on':''}" data-act="sel:${i}">${o.mode==='pics'||o.mode==='cf'?ic(catIcon(it.cat||it.n),'ico ls-ic'):chk(sel.includes(i))}<span class="ls-txt"><span>${it.n}</span>${o.mode==='pics'?`<span class="ls-sub">${(it.p*100).toFixed(0)}% margin</span>`:''}</span><span class="ls-v">${fmt(it.v,'$')}</span></div>`;}).join(''));
  },
  act(o,st,a,arg){
    let sel=(st.sel||o.sel||[]).slice();
    if(a==='sel'){const i=+arg;const k=sel.indexOf(i);if(k>=0)sel.splice(k,1);else sel.push(i);st.sel=sel;return true;}
    if(a==='rm'){st.sel=sel.filter(x=>x!==+arg);return true;}
    if(a==='open'){st.open=!st.open;return true;}
    if(a==='hx'){const i=+arg;const op=(st.open||[0,1]).slice();const k=op.indexOf(i);if(k>=0)op.splice(k,1);else op.push(i);st.open=op;return true;}
    if(a==='hy'){const ci=+arg;const kids=[0,1,2,3].map(s=>ci*10+s);const allOn=kids.every(k=>sel.includes(k));sel=sel.filter(k=>!kids.includes(k));if(!allOn)sel.push(...kids);st.sel=sel;return true;}
  }
};
/* ---------------- Input slicer (GA; formerly text slicer) ---------------- */
const OPS=['Contains any','Contains all','Does not contain any','Starts with any','Does not start with any','Is any','Is not any'];
E.islicer={
  draw(o,st){
    if(o.mode==='ttf')return H_('is',`<div class="sl-h"><span>Add a comment</span></div><div class="is-area">${st.sent?'':'Hold Q4 discount for Partner channel until review.'}</div><div class="is-row"><span class="is-note">${st.sent?'<span class="ok" aria-hidden="true">✓</span> Saved to the comments table':'Writes back through a user data function'}</span><button class="is-sub" data-act="send">${st.sent?'Submitted':'Submit'}</button></div>`);
    const pills=st.pills||o.pills;const op=st.op??o.op??0;
    return H_('is',`<div class="sl-h"><span>${o.field||'Product'}</span></div><div class="is-box"><button class="is-op" data-act="op" aria-label="Filter operator"><span class="is-opi">${['∋','∀','∌','⊢','⊬','=','≠'][op]}</span>${o.showOp?OPS[op]:''}<i aria-hidden="true">▾</i></button><span class="is-in">${o.num?'Type a value or range':'Type to filter'}</span><button class="is-go" aria-label="Apply">→</button></div>`+
      (st.oo?`<div class="sl-pop">${OPS.map((x,i)=>`<div class="sl-it${i===op?' cur':''}" data-act="opset:${i}">${x}</div>`).join('')}</div>`:'')+
      `<div class="is-pills">${pills.map((p,i)=>`<span class="pill-s">${esc(p)}<i data-act="rm:${i}" aria-label="Remove">✕</i></span>`).join('')}</div>`+
      `<div class="is-res">${o.num?'Matches orders where amount is '+pills.join(', '):`Showing products that ${OPS[op].toLowerCase()} ${pills.map(p=>'“'+p+'”').join(', ')}`}</div>`);
  },
  act(o,st,a,arg){
    if(a==='op'){st.oo=!st.oo;return true;}
    if(a==='opset'){st.op=+arg;st.oo=false;return true;}
    if(a==='rm'){const p=(st.pills||o.pills).slice();p.splice(+arg,1);st.pills=p.length?p:o.pills;return true;}
    if(a==='send'){st.sent=!st.sent;return true;}
  }
};

/* ---------------- Key influencers ---------------- */
E.keyinf={
  draw(o,st,W,H){
    const tab=st.tab||o.tab||'ki';const fi=st.f??0;
    const head=`<div class="ki-tabs"><button class="${tab==='ki'?'on':''}" data-act="tab:ki">Key influencers</button><button class="${tab==='seg'?'on':''}" data-act="tab:seg">Top segments</button></div>`;
    const q=o.cont?`What influences <b>Order value</b> to <b class="kisel">Increase</b>?`:`What influences <b>${KI.target}</b> to be <b class="kisel">${KI.val}</b>?`;
    if(tab==='seg'){return H_('ki',head+`<div class="ki-q">When is <b>${KI.target}</b> more likely to be <b class="kisel">${KI.val}</b>?</div><div class="ki-seg">`+KI.seg.map((s,i)=>`<div class="ki-bub" data-i="${i}" style="--s:${(.5+s.pop/1210*.5).toFixed(2)};--p:${s.p}" data-t="${tipA('Segment '+(i+1),[[s.p+'%',KI.target+' = '+KI.val,'c1'],[s.pop,'Customers in segment','muted']])}"><b>${s.p}%</b><span>Segment ${i+1}</span></div>`).join('')+`</div><div class="ki-segl">${KI.seg.slice(0,2).map((s,i)=>`<div><b>Segment ${i+1}</b> ${s.n}</div>`).join('')}</div>`);}
    const fs=o.cont?[{n:'Basket has 3+ items',x:'+$41',p:0},{n:'Customer is a returning member',x:'+$28',p:0},{n:'Channel is Partner',x:'+$19',p:0},{n:'Device is Desktop',x:'+$11',p:0}]:KI.f;
    const f=fs[fi]||fs[0];
    const bars=o.cont?[['Yes',212],['No',171]]:[[f.n.split(' is ')[1]||'Yes',f.p],['All others',Math.round(KI.base*.9*10)/10]];
    const mx=Math.max(...bars.map(b=>b[1]));const avg=o.cont?184:KI.base;
    const ch=`<svg class="ki-ch v" viewBox="0 0 220 150" font-size="10">`+bars.map((b,i)=>{const h=b[1]/mx*96;return `<path class="m" data-i="${i}" d="${bp(48+i*92,124-h,44,h,3,'t')}" style="fill:${i?'var(--muted-mark)':'var(--c1)'}"/><text x="${70+i*92}" y="${n1(118-h)}" text-anchor="middle" class="lb">${o.cont?'$'+b[1]:b[1]+'%'}</text><text x="${70+i*92}" y="138" text-anchor="middle" class="tk">${esc(trunc(b[0],86,10))}</text>`;}).join('')+`<line class="ref" x1="30" x2="214" y1="${n1(124-avg/mx*96)}" y2="${n1(124-avg/mx*96)}"/><text class="reft" x="214" y="${n1(120-avg/mx*96)}" text-anchor="end">Average ${o.cont?'$'+avg:avg+'%'}</text><line class="bl" x1="30" x2="214" y1="124" y2="124"/></svg>`;
    return H_('ki',head+`<div class="ki-q">${q}</div><div class="ki-body"><div class="ki-list">`+fs.map((x,i)=>`<button class="ki-f${i===fi?' on':''}" data-act="f:${i}"><span class="ki-b">${o.cont?x.x:x.x+'x'}</span><span>${x.n}</span></button>`).join('')+`</div><div class="ki-r"><div class="ki-rt">${o.cont?`When <b>${f.n.toLowerCase()}</b>, average order value increases by <b>${f.x}</b>`:`When <b>${f.n.toLowerCase()}</b>, the likelihood of ${KI.target} being ${KI.val} increases by <b>${f.x}x</b>`}</div>${ch}</div></div>`);
  },
  act(o,st,a,arg){if(a==='tab'){st.tab=arg;return true;}if(a==='f'){st.f=+arg;return true;}}
};

/* ---------------- Decomposition tree ---------------- */
E.decomp={
  draw(o,st,W,H){
    /* sel = chosen node per level; levels past the explicit picks are chosen by the AI split when o.ai is set */
    const lv=['Region','Country','City'];const ai=o.ai||null;
    const sel=(st.sel||o.sel||[0]).slice();
    const cols=[{h:'Sales',items:[{n:'Total',v:agg(HG.root)[0]}],sel:0,root:true}];
    let cur=HG.root;
    for(let l=0;l<3&&cur&&cur.c;l++){
      const items=cur.c.map(c=>({n:c.n,v:agg(c)[0],ly:agg(c)[2],node:c}));
      if(o.rel)items.forEach(it=>{it.r=it.v/it.ly-1;});
      items.sort((a,b)=>o.rel?b.r-a.r:b.v-a.v);
      let si=sel[l];const byAI=!!ai&&si==null;
      if(byAI)si=ai==='low'?items.length-1:0;
      cols.push({h:lv[l],items,sel:si==null?null:si,lvl:l,ai:byAI});
      if(si==null)break;
      cur=items[si]&&items[si].node;
    }
    const shown=cols;
    return H_('dt',shown.map((c,ci)=>{const mx=Math.max(...c.items.map(x=>o.rel&&!c.root?Math.abs(x.r):x.v));
      return `<div class="dt-col"><div class="dt-h">${c.ai?`<span class="dt-ai" title="AI split">${'<svg viewBox="0 0 24 24" class="ico sm" aria-hidden="true"><path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-4 10.5V16h8v-2.5A6 6 0 0 0 12 3z"/></svg>'}</span>`:''}${c.h}${c.ai?`<span class="dt-ait">${ai==='low'?'Low value':'High value'}</span>`:''}</div>`+c.items.slice(0,6).map((it,ii)=>{const val=o.rel&&!c.root?it.r:it.v;const w=Math.max(4,Math.abs(val)/mx*100);
        return `<div class="dt-n${c.sel===ii?' on':''}${c.sel!=null&&c.sel!==ii?' dim':''}"${c.root?'':` data-act="pick:${c.lvl}:${ii}"`} data-t="${tipA(it.n,[[fmt(it.v,'$'),'Sales',1]].concat(o.rel&&!c.root?[[fmtS(it.r*100,'%'),'vs last year','muted']]:[]))}"><div class="dt-l"><span>${esc(it.n)}</span><b>${o.rel&&!c.root?fmtS(val*100,'%'):fmt(it.v,'$')}</b></div><div class="dt-bar"><i style="width:${w}%"></i></div></div>`;}).join('')+(c.items.length>6?`<div class="dt-more">+${c.items.length-6} more</div>`:'')+`</div>`;}).join(''));
  },
  act(o,st,a,arg){if(a==='pick'){const [l,i]=arg.split(':').map(Number);const sel=(st.sel||o.sel||[0]).slice(0,l);sel[l]=i;st.sel=sel;return true;}}
};

/* ---------------- Narrative ---------------- */
const dv=(t,c)=>`<mark class="dv${c?' '+c:''}">${t}</mark>`;
E.narr={draw(o){
  const best=TY.indexOf(Math.max(...TY));const g=pctCh(TYS,LYS);
  if(o.mode==='copilot')return H_('nar cop',`<div class="nar-h"><span class="spark-ic" aria-hidden="true">✦</span>Summary <span class="nar-tag">Copilot</span></div><ul><li>Sales reached ${dv(fmt(TYS,'$'))}, ${dv(fmtS(g,'%'),'up')} on 2024, led by ${dv('Bikes')}.</li><li>${dv(MON[best])} was the strongest month at ${dv(fmt(TY[best],'$'))}.</li><li>${dv('Europe')} grew fastest; ${dv('Middle East & Africa')} missed target by ${dv('6%','down')}.</li><li>Return rate improved to ${dv('2.8%','up')} from 3.1%.</li></ul><div class="nar-f">AI-generated content may be incorrect · Ask a follow-up</div>`);
  if(o.mode==='visual')return H_('nar nvis',`<div class="nar-ch">${E.cart.draw({cats:MON,layers:[{t:'line',s:[{n:'Sales',v:TY}],mk:'end'}],u:'$'},{},360,150)}</div><p>Sales trended ${dv('upward')} through 2025, rising from ${dv(fmt(TY[0],'$'))} in January to ${dv(fmt(TY[11],'$'))} in December. The largest month-over-month jump was ${dv('+12.4%','up')} into November.</p>`);
  if(o.mode==='custom')return H_('nar',`<p>Our team closed <b>2025</b> with ${dv(fmt(TYS,'$'))} in sales, ${dv(fmtS(g,'%'),'up')} vs last year, against a target of ${dv(fmt(TYS*.97,'$'))}.</p><p>Profit margin held at ${dv((PRS/TYS*100).toFixed(1)+'%')}. <span class="nar-edit">Values update with filters and slicers.</span></p>`);
  return H_('nar',`<p>Sales for 2025 totaled ${dv(fmt(TYS,'$'))}, an increase of ${dv(fmtS(g,'%'),'up')} over 2024. ${dv('Bikes')} contributed ${dv((CAT4S[0]/sumA(CAT4S)*100).toFixed(0)+'%')} of sales.</p><p>${dv(MON[best])} had the highest sales at ${dv(fmt(TY[best],'$'))}, while ${dv('February')} was the lowest. Across regions, ${dv(REG4[REG4S.indexOf(Math.max(...REG4S))])} led with ${dv(fmt(Math.max(...REG4S),'$'))}.</p>`);
}};
/* ---------------- Q&A (retiring Dec 2026) ---------------- */
const QS=[['top 5 products by sales',{cats:TOPP.slice(0,5).map(p=>p.n),dir:'h',layers:[{t:'bar',s:[{n:'Sales',v:TOPP.slice(0,5).map(p=>p.v[0])}],labels:'out'}],u:'$'}],['sales by month as line chart',{cats:MON,layers:[{t:'line',s:[{n:'Sales',v:TY}]}],u:'$'}],['profit by category as column chart',{cats:CAT4,layers:[{t:'bar',s:[{n:'Profit',v:CAT4P}],labels:'out'}],u:'$'}]];
E.qna={draw(o,st,W,H){
  if(o.mode==='retire')return H_('qa ret',`<div class="qa-ban"><b>Q&A retires in December 2026.</b> Existing Q&A visuals stop working and are removed.</div><div class="qa-map"><div><span>Q&A visual in reports</span><b>→ Copilot in Power BI reports</b></div><div><span>Q&A on dashboards</span><b>→ Copilot standalone experience</b></div><div><span>Q&A setup (synonyms, teach Q&A)</span><b>→ Prep data for AI</b></div></div>`);
  const qi=st.q??o.q??0;const fs=FS(W);
  const chips=QS.map((q,i)=>`<button class="qa-chip${i===qi?' on':''}" data-act="q:${i}">${q[0]}</button>`).join('');
  return H_('qa',`<div class="qa-box"><span class="qa-i" aria-hidden="true">?</span><span class="qa-t">${QS[qi][0]}</span>${o.convert?'<button class="qa-cv" title="Turn this Q&A result into a standard visual" aria-label="Convert to standard visual">⇄</button>':''}</div><div class="qa-chips">${chips}</div><div class="qa-res">${E.cart.draw(QS[qi][1],{},W,Math.round(H*.62))}</div>`);
},act(o,st,a,arg){if(a==='q'){st.q=+arg;return true;}}};

/* ---------------- Paginated report visual ---------------- */
E.pag={draw(o,st){
  const pg=st.pg||1;
  const tb=`<div class="pg-tb"><span class="pg-b">◀</span><span>Page <b>${pg}</b> of 4</span><span class="pg-b" data-act="pg">▶</span><span class="sp"></span>${o.exp?`<span class="pg-x on">Export ▾</span>`:'<span class="pg-x">Export ▾</span>'}</div>`;
  if(o.mode==='params')return H_('pg',tb+`<div class="pg-par"><label>Region<span>Europe ▾</span></label><label>Year<span>2025 ▾</span></label><button class="pg-run">View report</button></div><div class="pg-note">Parameters can be bound to report fields, so slicers drive the paginated report.</div>`+pgTable(3));
  if(o.exp)return H_('pg',tb+`<div class="pg-menu">${['PDF','Excel','Word','PowerPoint','CSV','XML','MHTML'].map(x=>`<div>${x}</div>`).join('')}</div>`+pgTable(4));
  if(o.mode==='group')return H_('pg',tb+`<div class="pg-page"><div class="pg-title">Sales detail by region</div>${HG.root.c.slice(0,2).map(r=>`<div class="pg-grp">${r.n}</div><table class="pg-t">${r.c.slice(0,3).map(c=>`<tr><td>${c.n}</td><td>${fmt(agg(c)[1],'')} customers</td><td>${fmt(agg(c)[0],'$')}</td></tr>`).join('')}<tr class="pg-sub"><td>Subtotal</td><td></td><td>${fmt(agg(r)[0],'$')}</td></tr></table>`).join('')}</div>`);
  return H_('pg',tb+`<div class="pg-page"><div class="pg-hd"><div><div class="pg-title">Invoice INV-20418</div><div class="pg-sm">Northgate Cycles · Due Dec 31, 2025</div></div><div class="pg-logo">${ic('bike','ico')}</div></div>`+pgTable(4,true)+`</div>`);
}};
function pgTable(n,inv){return `<table class="pg-t"><tr class="pg-th"><td>Item</td><td>Qty</td><td>Amount</td></tr>${TOPP.slice(0,n).map(p=>`<tr><td>${p.n}</td><td>${Math.round(p.v[2]/400)}</td><td>${fmt(p.v[0]/400,'$')}</td></tr>`).join('')}${inv?`<tr class="pg-sub"><td>Total due</td><td></td><td>${fmt(sumA(TOPP.slice(0,n).map(p=>p.v[0]/400)),'$')}</td></tr>`:''}</table>`;}
/* ---------------- Power Apps visual ---------------- */
E.papps={draw(o,st){
  if(o.mode==='gallery')return H_('pa',`<div class="pa-h">${ic('store','ico sm')} Store follow-ups</div>`+['Northgate Cycles','Ridgeway Sports','Harbor Bikes'].map((n,i)=>`<div class="pa-g" data-act="pick:${i}"><div><b>${n}</b><span>${['Call back about bulk order','Send e-bike demo dates','Confirm warranty claim'][i]}</span></div><span class="pa-s ${['warn','c1','good'][i]}">${['Due today','This week','Done'][i]}</span></div>`).join(''));
  if(o.mode==='approve')return H_('pa',`<div class="pa-h">${ic('handshake','ico sm')} Discount request</div><div class="pa-ctx"><span>Context from report filters</span><b>Partner · Europe · Q4</b></div><div class="pa-kv"><span>Requested</span><b>12% on E-bike 300</b></div><div class="pa-kv"><span>Margin after</span><b class="down">9.4%</b></div><div class="pa-btns"><button class="pa-btn ok" data-act="ok">${st.done==='ok'?'✓ Approved':'Approve'}</button><button class="pa-btn" data-act="no">${st.done==='no'?'Rejected':'Reject'}</button></div>`);
  return H_('pa',`<div class="pa-h">${ic('cart','ico sm')} Log a follow-up</div><label class="pa-f">Account<span>Northgate Cycles</span></label><label class="pa-f">Next step<span>Quote for 40 × Road 200</span></label><label class="pa-f">Owner<span>Priya N.</span></label><button class="pa-btn ok" data-act="save">${st.saved?'✓ Saved to Dataverse':'Save'}</button>`);
},act(o,st,a){if(a==='save'){st.saved=!st.saved;return true;}if(a==='ok'||a==='no'){st.done=a;return true;}}};
/* ---------------- Power Automate visual ---------------- */
E.pauto={draw(o,st){
  if(o.mode==='flow')return H_('pf',`<div class="pf-step"><span class="pf-i b">▶</span><div><b>Power BI button clicked</b><span>Passes Region, Product</span></div></div><div class="pf-ar" aria-hidden="true"></div><div class="pf-step"><span class="pf-i c">✉</span><div><b>Send an email (V2)</b><span>To: regional manager</span></div></div><div class="pf-ar" aria-hidden="true"></div><div class="pf-step"><span class="pf-i d">#</span><div><b>Post message in a chat</b><span>Channel: Sales alerts</span></div></div>`);
  if(o.mode==='status')return H_('pf c',`<button class="pf-run done">✓ Flow ran successfully</button><div class="pf-log"><div><span>Started</span><b>10:42:07</b></div><div><span>Rows sent</span><b>14</b></div><div><span>Duration</span><b>2.1 s</b></div></div>`);
  return H_('pf c',`<button class="pf-run${st.ran?' done':''}" data-act="run">${st.ran?'✓ Sent to 4 regional managers':'Notify regional managers'}</button><div class="pf-hint">Runs a flow with the rows currently filtered in the report (up to 1,000)</div>`);
},act(o,st,a){if(a==='run'){st.ran=!st.ran;return true;}}};

/* ---------------- R and Python visuals (static image output) ---------------- */
function plotFrame(W,H,kind,inner,xl,yl){
  /* R visuals render like ggplot2 theme_grey; Python like seaborn darkgrid; both are images, so they ignore the report theme */
  const p=kind==='r'?{bg:'#ffffff',panel:'#ebebeb',grid:'#ffffff',ink:'#333333'}:{bg:'#ffffff',panel:'#eaeaf2',grid:'#ffffff',ink:'#262626'};
  return `<svg class="img-plot" viewBox="0 0 ${W} ${H}" font-size="${FS(W)}"><rect width="${W}" height="${H}" fill="${p.bg}"/><rect x="40" y="10" width="${W-50}" height="${H-40}" fill="${p.panel}"/>${[0,1,2,3,4].map(k=>`<line x1="40" x2="${W-10}" y1="${n1(10+(H-40)*k/4)}" y2="${n1(10+(H-40)*k/4)}" stroke="${p.grid}" stroke-width="${k%2?0.6:1.2}"/>`).join('')}${inner(p)}<text x="${n1(W/2)}" y="${H-6}" text-anchor="middle" fill="${p.ink}" font-family="Helvetica, Arial, sans-serif">${xl}</text><text x="12" y="${n1(H/2-10)}" fill="${p.ink}" font-family="Helvetica, Arial, sans-serif" transform="rotate(-90 12 ${n1(H/2-10)})" text-anchor="middle">${yl}</text></svg>`;
}
const GG=['#F8766D','#7CAE00','#00BFC4','#C77CFF'];const SNS=['#4c72b0','#dd8452','#55a868','#c44e52'];
E.rpy={draw(o,st,W,H){
  const r=rng(9);const X0=40,X1=W-10,Y0=10,Y1=H-30;const cw=(X1-X0)/4;
  let code='',img='';
  if(o.mode==='box'){code=`library(ggplot2)\nggplot(dataset, aes(Category, Margin, fill = Category)) +\n  geom_boxplot()`;
    img=plotFrame(W,H,'r',p=>HP.root.c.map((c,i)=>{const ms=leaves(c).map(l=>l.v[1]/l.v[0]*100).sort((a,b)=>a-b);const Y=v=>Y1-(v-0)/50*(Y1-Y0);const q1=ms[Math.floor(ms.length*.25)],q3=ms[Math.floor(ms.length*.75)],md=ms[ms.length>>1];const x=X0+cw*i+cw*.25,w=cw*.5;
      return `<line x1="${n1(x+w/2)}" x2="${n1(x+w/2)}" y1="${n1(Y(ms[0]))}" y2="${n1(Y(ms[ms.length-1]))}" stroke="${p.ink}"/><rect x="${n1(x)}" y="${n1(Y(q3))}" width="${n1(w)}" height="${n1(Y(q1)-Y(q3))}" fill="${GG[i]}" stroke="${p.ink}"/><line x1="${n1(x)}" x2="${n1(x+w)}" y1="${n1(Y(md))}" y2="${n1(Y(md))}" stroke="${p.ink}" stroke-width="2"/><text x="${n1(x+w/2)}" y="${n1(Y1+12)}" text-anchor="middle" fill="${p.ink}" font-size="9">${c.n}</text>`;}).join(''),'Category','Margin %');}
  else if(o.mode==='density'){code=`ggplot(dataset, aes(DeliveryDays, fill = Carrier)) +\n  geom_density(alpha = 0.5)`;
    img=plotFrame(W,H,'r',p=>[1.6,2.8,4.6,7].map((m,i)=>{const sd=[.5,.8,1.2,2][i];let d='';for(let k=0;k<=60;k++){const xv=k/60*12;const y=Math.exp(-((xv-m)**2)/(2*sd*sd))/(sd*2.5);d+=(k?'L':'M')+n1(X0+xv/12*(X1-X0))+','+n1(Y1-y*(Y1-Y0)*.9);}return `<path d="${d}L${X1},${Y1}L${X0},${Y1}Z" fill="${GG[i]}" fill-opacity=".5" stroke="${p.ink}" stroke-width=".6"/>`;}).join(''),'Delivery days','Density');}
  else if(o.mode==='corr'){code=`library(corrplot)\ncorrplot(cor(dataset), method = "color")`;
    const v=['Sales','Profit','Units','Price','Rating'];const M=[[1,.86,.74,.31,.22],[.86,1,.58,.52,.18],[.74,.58,1,-.44,.09],[.31,.52,-.44,1,.27],[.22,.18,.09,.27,1]];
    img=plotFrame(W,H,'r',p=>{const s=Math.min((X1-X0),(Y1-Y0))/5;const ox=X0+((X1-X0)-s*5)/2;return M.map((row,i)=>row.map((c,j)=>`<rect x="${n1(ox+j*s)}" y="${n1(Y0+i*s)}" width="${n1(s-1)}" height="${n1(s-1)}" fill="${c>=0?`rgba(33,102,172,${Math.abs(c)})`:`rgba(178,24,43,${Math.abs(c)})`}"/><text x="${n1(ox+j*s+s/2)}" y="${n1(Y0+i*s+s/2+3)}" text-anchor="middle" font-size="8" fill="${Math.abs(c)>.5?'#fff':'#333'}">${c.toFixed(2)}</text>`).join('')).join('');},'','');}
  else if(o.mode==='facet'){code=`ggplot(dataset, aes(Spend, Revenue)) +\n  geom_point() + geom_smooth(method = "lm") +\n  facet_wrap(~ Format)`;
    img=plotFrame(W,H,'r',p=>[0,1,2].map(g=>{const pts=STORES.filter(s=>s.g===g);const fx=X0+g*(X1-X0)/3+4,fw=(X1-X0)/3-8;const X=v=>fx+v/110*fw,Y=v=>Y1-v/1100*(Y1-Y0-14);
      return `<rect x="${n1(fx)}" y="${Y0}" width="${n1(fw)}" height="12" fill="#d9d9d9"/><text x="${n1(fx+fw/2)}" y="${Y0+9}" text-anchor="middle" font-size="8" fill="${p.ink}">${['Flagship','Mall','Outlet'][g]}</text>`+pts.map(s=>`<circle cx="${n1(X(s.x))}" cy="${n1(Y(s.y))}" r="1.8" fill="${p.ink}"/>`).join('')+`<line x1="${n1(X(10))}" y1="${n1(Y(10*[7,8,9.5][g]+20))}" x2="${n1(X(100))}" y2="${n1(Y(100*[7,8,9.5][g]+20))}" stroke="#3366FF" stroke-width="1.6"/>`;}).join(''),'Ad spend ($K)','Revenue ($K)');}
  else if(o.mode==='violin'){code=`import seaborn as sns\nsns.violinplot(data=dataset, x="Channel", y="OrderValue")`;
    img=plotFrame(W,H,'py',p=>[0,1,2].map(i=>{const cx=X0+(X1-X0)/3*(i+.5),m=[.55,.45,.62][i];let L='',R='';for(let k=0;k<=30;k++){const t=k/30;const y=Y1-6-t*(Y1-Y0-12);const w=Math.exp(-((t-m)**2)/(2*.025))*(X1-X0)/8+Math.exp(-((t-m+.25)**2)/(2*.01))*(X1-X0)/18;L+=(k?'L':'M')+n1(cx-w)+','+n1(y);R=`L${n1(cx+w)},${n1(y)}`+R;}return `<path d="${L}${R.replace(/^L/,'L')}Z" fill="${SNS[i]}" stroke="#3a3a3a" stroke-width=".8"/><line x1="${n1(cx)}" x2="${n1(cx)}" y1="${n1(Y1-6-(m+.18)*(Y1-Y0-12))}" y2="${n1(Y1-6-(m-.2)*(Y1-Y0-12))}" stroke="#3a3a3a" stroke-width="3"/><circle cx="${n1(cx)}" cy="${n1(Y1-6-m*(Y1-Y0-12))}" r="2" fill="#fff"/><text x="${n1(cx)}" y="${n1(Y1+12)}" text-anchor="middle" font-size="9" fill="${p.ink}">${CH[i]}</text>`;}).join(''),'Channel','Order value');}
  else if(o.mode==='reg'){code=`sns.regplot(data=dataset, x="Spend", y="Revenue", ci=95)`;
    img=plotFrame(W,H,'py',p=>{const X=v=>X0+v/110*(X1-X0),Y=v=>Y1-v/1100*(Y1-Y0);const a=7.6,b=26;const up=[],dn=[];for(let v=10;v<=105;v+=5){const e=40+Math.abs(v-55)*1.6;up.push([X(v),Y(a*v+b+e)]);dn.push([X(v),Y(a*v+b-e)]);}
      return `<path d="${linePath(up)}${linePath(dn.reverse()).replace(/^M/,'L')}Z" fill="${SNS[0]}" fill-opacity=".2"/>`+STORES.map(s=>`<circle cx="${n1(X(s.x))}" cy="${n1(Y(s.y))}" r="2.6" fill="${SNS[0]}" fill-opacity=".8"/>`).join('')+`<line x1="${n1(X(10))}" y1="${n1(Y(a*10+b))}" x2="${n1(X(105))}" y2="${n1(Y(a*105+b))}" stroke="${SNS[0]}" stroke-width="2"/>`;},'Spend ($K)','Revenue ($K)');}
  else if(o.mode==='heat'){code=`sns.heatmap(dataset.pivot("Weekday", "Hour", "Orders"), cmap="rocket_r")`;
    const days=['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
    img=plotFrame(W,H,'py',p=>{const cw2=(X1-X0)/12,ch=(Y1-Y0)/7;let s='';days.forEach((d,i)=>{for(let h=0;h<12;h++){const v=Math.max(0,Math.min(1,.25+.55*Math.sin((h-2)/11*Math.PI)+(i>4?.2:0)+(r()-.5)*.2));const c=`rgb(${Math.round(250-v*170)},${Math.round(230-v*200)},${Math.round(200-v*120)})`;s+=`<rect x="${n1(X0+h*cw2)}" y="${n1(Y0+i*ch)}" width="${n1(cw2+.4)}" height="${n1(ch+.4)}" fill="${c}"/>`;}s+=`<text x="${X0-4}" y="${n1(Y0+i*ch+ch/2+3)}" text-anchor="end" font-size="8" fill="${p.ink}">${d}</text>`;});return s;},'Hour of day (8–19)','');}
  else{code=`pd.plotting.scatter_matrix(dataset[["Sales", "Profit", "Units"]])`;
    img=plotFrame(W,H,'py',p=>{const n=3,cwm=(X1-X0)/n,chm=(Y1-Y0)/n;let s='';const D=PRODS.map(x=>[x.v[0],x.v[1],x.v[2]]);const mx=[0,1,2].map(k=>Math.max(...D.map(d=>d[k])));
      for(let i=0;i<n;i++)for(let j=0;j<n;j++){const x0=X0+j*cwm+3,y0=Y0+i*chm+3,w=cwm-6,h=chm-6;s+=`<rect x="${n1(x0)}" y="${n1(y0)}" width="${n1(w)}" height="${n1(h)}" fill="#fff" fill-opacity=".55"/>`;
        if(i===j){const bins=[0,0,0,0,0,0];D.forEach(d=>{bins[Math.min(5,Math.floor(d[i]/mx[i]*6))]++;});const bm=Math.max(...bins);bins.forEach((b,k)=>{s+=`<rect x="${n1(x0+k*w/6+1)}" y="${n1(y0+h-b/bm*h)}" width="${n1(w/6-2)}" height="${n1(b/bm*h)}" fill="${SNS[0]}"/>`;});}
        else D.forEach(d=>{s+=`<circle cx="${n1(x0+d[j]/mx[j]*w)}" cy="${n1(y0+h-d[i]/mx[i]*h)}" r="1.4" fill="${SNS[0]}"/>`;});}return s;},'Sales · Profit · Units','');}
  return H_('rp'+(o.code?' with-code':''),`<div class="rp-img">${img}</div>`+(o.code!==false?`<pre class="rp-code"><code>${esc(code)}</code></pre>`:''));
}};

/* ---------------- Image visual ---------------- */
E.image={draw(o,st,W,H){
  const p=st.p??0;const prods=[['E-bike 300','bike','$3,240'],['Helmet 100','helmet','$129'],['Jacket 200','shirt','$189']];
  if(o.mode==='static')return H_('im',`<div class="im-hero"><div class="im-mark">${ic('bike','ico big')}</div><div><div class="im-t">Northgate Cycles</div><div class="im-s">Regional sales review</div></div></div>`);
  if(o.mode==='svg')return H_('im c',`<div class="im-cap">Image from a DAX measure (data category: Image URL)</div><div class="im-svgm">${spark(TY,{w:260,h:70,c:1})}</div><code class="im-code">Trend SVG = "data:image/svg+xml;utf8," &amp; …</code>`);
  if(o.mode==='action')return H_('im c',`<button class="im-btn" data-act="go">${ic('globe','ico big')}<span>${st.went?'Opened the store map page':'Open store map'}</span></button><div class="im-cap">Image with a page-navigation action</div>`);
  return H_('im dyn',`<div class="im-pick">${prods.map((x,i)=>`<button class="${i===p?'on':''}" data-act="p:${i}">${x[0]}</button>`).join('')}</div><div class="im-prod">${ic(prods[p][1],'ico huge')}<div><div class="im-t">${prods[p][0]}</div><div class="im-s">${prods[p][2]} · image URL bound to the selected product</div></div></div>`);
},act(o,st,a,arg){if(a==='p'){st.p=+arg;return true;}if(a==='go'){st.went=!st.went;return true;}}};

/* ---------------- Buttons & navigators ---------------- */
E.btns={draw(o,st){
  const pg=st.pg??0;const pages=['Overview','Regions','Products','Customers'];
  if(o.mode==='states')return H_('bt',`<div class="bt-row"><div class="bt-col"><span class="bt-cap">Default</span><button class="btn">Details</button></div><div class="bt-col"><span class="bt-cap">On hover</span><button class="btn hov">Details</button></div><div class="bt-col"><span class="bt-cap">On press</span><button class="btn prs">Details</button></div><div class="bt-col"><span class="bt-cap">Disabled</span><button class="btn dis" disabled>Details</button></div></div><div class="bt-acts">Actions: Back · Bookmark · Drill through · Page navigation · Q&A · Web URL · Apply / clear all slicers · Data function</div>`);
  if(o.mode==='bookmark'){const bm=st.bm??0;return H_('bt',`<div class="bm">${['Sales view','Margin view','Map view'].map((b,i)=>`<button class="${i===bm?'on':''}" data-act="bm:${i}">${b}</button>`).join('')}</div><div class="bt-pv">${['Columns showing sales by region','Line showing margin trend','Bubble map of store sales'][bm]}</div>`);}
  if(o.mode==='slicers')return H_('bt',`<div class="bt-row"><button class="btn pri" data-act="apply">${st.ap?'✓ Applied':'Apply all slicers'}</button><button class="btn" data-act="clear">Clear all slicers</button></div><div class="bt-pv">Lets readers set several slicers, then send one query instead of one per click.</div>`);
  if(o.mode==='ttf')return H_('bt',`<div class="bt-form"><div class="bt-in">Discount % <b>12</b></div><button class="btn pri" data-act="apply">${st.ap?'✓ Updated 1 row':'Update price'}</button></div><div class="bt-pv">A button with the Data function action runs a Fabric user data function (translytical task flow).</div>`);
  return H_('bt',`<div class="pgn">${pages.map((p,i)=>`<button class="${i===pg?'on':''}" data-act="pg:${i}">${p}</button>`).join('')}</div><div class="bt-pv">Page navigator: one button per visible report page, kept in sync automatically.</div>`);
},act(o,st,a,arg){if(a==='pg'){st.pg=+arg;return true;}if(a==='bm'){st.bm=+arg;return true;}if(a==='apply'){st.ap=!st.ap;return true;}if(a==='clear'){st.ap=false;return true;}}};
/* ---------------- Text box & shapes ---------------- */
E.texts={draw(o){
  if(o.mode==='shapes')return H_('tx sh',`<div class="sh-panel"><span>Rectangle (rounded) as a panel</span></div><div class="sh-row"><svg viewBox="0 0 60 40" aria-hidden="true"><rect x="4" y="6" width="52" height="28" rx="8" class="shp"/></svg><svg viewBox="0 0 60 40" aria-hidden="true"><ellipse cx="30" cy="20" rx="24" ry="14" class="shp"/></svg><svg viewBox="0 0 60 40" aria-hidden="true"><path d="M6 14h30V6l18 14-18 14v-8H6z" class="shp"/></svg><svg viewBox="0 0 60 40" aria-hidden="true"><path d="M30 4l24 32H6z" class="shp"/></svg></div>`);
  if(o.mode==='callout')return H_('tx',`<div class="tx-call"><div class="tx-bub">Black Friday week drove <b>38%</b> of November sales</div><svg viewBox="0 0 200 60" class="tx-mini" aria-hidden="true"><path d="${linePath(TY.map((v,i)=>[8+i*16.7,54-(v-Math.min(...TY))/(Math.max(...TY)-Math.min(...TY))*44]))}" class="spl"/><circle cx="${n1(8+10*16.7)}" cy="${n1(54-(TY[10]-Math.min(...TY))/(Math.max(...TY)-Math.min(...TY))*44)}" r="4" class="tx-dot"/></svg></div>`);
  if(o.mode==='banner')return H_('tx ban',`<div class="ban-l"><div class="ban-t">Sales performance</div><div class="ban-s">FY2025 · All regions · Updated daily</div></div><div class="ban-k"><div><b>${fmt(TYS,'$')}</b><span>Sales</span></div><div><b>${fmtS(pctCh(TYS,LYS),'%')}</b><span>vs LY</span></div></div>`);
  return H_('tx',`<div class="tx-box"><p>Sales reached <b class="tx-dv">${fmt(TYS,'$')}</b> this year, <b class="tx-dv up">${fmtS(pctCh(TYS,LYS),'%')}</b> on last year.</p><p class="tx-sub">Values inside the text box are bound to measures and update with filters.</p></div>`);
}};
