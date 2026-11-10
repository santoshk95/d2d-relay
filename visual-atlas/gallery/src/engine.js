/* ============================================================
   Chart engine — every renderer returns markup for (o, st, W, H)
   o = variant options, st = live state (drill, zoom, selection)
   ============================================================ */
const E={look:'soft'};
let UID=0;
const tk=c=>c==null?'c1':typeof c==='number'?'c'+(((c-1)%8+8)%8+1):String(c);
const kc=c=>' k-'+tk(c);
const ki=c=>' ki-'+tk(c);
/* 3D prism: front face + side + top, grouped so animation, hover and highlight treat it as one mark */
function prism(x,y,w,h,ct,cls,i,dl,V,dep,extra){
  x=n1(x);y=n1(y);w=n1(Math.max(w,.5));h=n1(Math.max(h,.5));const d=Math.max(2.5,Math.min(dep,(V?w:h)*.55+1.5)),dx=n1(d),dy=n1(d*.62);
  return `<g class="${cls}${kc(ct)}" data-i="${i}"${extra||''} style="${dl}"><path class="pz sd${kc(ct)}" d="M${n1(x+w)},${y}l${dx},${-dy}v${h}l${-dx},${dy}Z"/><path class="pz tp${kc(ct)}" d="M${x},${y}l${dx},${-dy}h${w}l${-dx},${dy}Z"/><path class="fr${V?'':' frh'}${kc(ct)}" d="M${x},${y}h${w}v${h}h${-w}Z" style="fill:${col(ct)}"/></g>`;
}
const n1=v=>Math.round(v*10)/10;
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const sumA=a=>a.reduce((s,v)=>s+(v||0),0);
const col=c=>c==null?'var(--c1)':typeof c==='number'?`var(--c${((c-1)%8+8)%8+1})`:(c[0]==='#'||c.startsWith('var(')||c.startsWith('color-mix'))?c:`var(--${c})`;
const TW=(s,fs)=>String(s).length*fs*.6;
const trunc=(s,w,fs)=>{s=String(s);if(TW(s,fs)<=w)return s;const k=Math.max(1,Math.floor(w/(fs*.6))-1);return s.slice(0,k)+'…';};
const trimN=(x,d)=>String(+x.toFixed(d));
function fmt(v,u){
  if(v==null||isNaN(v))return '–';
  if(u==='%')return (Math.abs(v)<10&&v%1?v.toFixed(1):Math.round(v))+'%';
  if(u==='pct')return Math.round(v*100)+'%';
  if(u==='pt')return (v>0?'+':v<0?'−':'')+Math.abs(v).toFixed(1)+' pt';
  if(u==='$.')return (v<0?'−':'')+'$'+Math.abs(v).toFixed(2);
  const a=Math.abs(v),sg=v<0?'−':'';let t;
  if(a>=1e9)t=trimN(a/1e9,1)+'B';
  else if(a>=1e6)t=trimN(a/1e6,a>=1e7?1:2)+'M';
  else if(a>=1e4)t=trimN(a/1e3,a>=1e5?0:1)+'K';
  else if(a>=1e3)t=Math.round(a).toLocaleString('en-US');
  else t=trimN(a,a<10&&a%1?1:0);
  return sg+(u==='$'?'$':'')+t+(u==='d'?' d':'');
}
const fmtS=(v,u)=>(v>0?'+':'')+fmt(v,u);
function ticks(lo,hi,n){
  if(!(hi>lo)){hi=lo+1;}
  const raw=(hi-lo)/Math.max(1,n),mag=Math.pow(10,Math.floor(Math.log10(raw))),f=raw/mag;
  const step=(f>5?10:f>2?5:f>1?2:1)*mag;
  const a=Math.floor(lo/step+1e-9)*step,b=Math.ceil(hi/step-1e-9)*step,t=[];
  for(let v=a;v<=b+step*1e-6;v+=step)t.push(Math.round(v/step)*step);
  return {lo:a,hi:b,t};
}
/* bar with a rounded data-end only (square at the baseline) */
function bp(x,y,w,h,r,end){
  x=n1(x);y=n1(y);w=n1(Math.max(w,0));h=n1(Math.max(h,0));
  r=Math.min(r,w/2,h/2);
  if(r<.6||end==='none')return `M${x},${y}h${w}v${h}h${-w}Z`;
  const X=n1(x+w),Y=n1(y+h);
  if(end==='t')return `M${x},${Y}V${n1(y+r)}Q${x},${y} ${n1(x+r)},${y}H${n1(X-r)}Q${X},${y} ${X},${n1(y+r)}V${Y}Z`;
  if(end==='b')return `M${x},${y}H${X}V${n1(Y-r)}Q${X},${Y} ${n1(X-r)},${Y}H${n1(x+r)}Q${x},${Y} ${x},${n1(Y-r)}Z`;
  if(end==='r')return `M${x},${y}H${n1(X-r)}Q${X},${y} ${X},${n1(y+r)}V${n1(Y-r)}Q${X},${Y} ${n1(X-r)},${Y}H${x}Z`;
  if(end==='l')return `M${X},${y}H${n1(x+r)}Q${x},${y} ${x},${n1(y+r)}V${n1(Y-r)}Q${x},${Y} ${n1(x+r)},${Y}H${X}Z`;
  /* all corners */
  return `M${n1(x+r)},${y}H${n1(X-r)}Q${X},${y} ${X},${n1(y+r)}V${n1(Y-r)}Q${X},${Y} ${n1(X-r)},${Y}H${n1(x+r)}Q${x},${Y} ${x},${n1(Y-r)}V${n1(y+r)}Q${x},${y} ${n1(x+r)},${y}Z`;
}
const linePath=p=>p.map((q,i)=>(i?'L':'M')+n1(q[0])+','+n1(q[1])).join('');
function monoPath(p){
  const n=p.length;if(n<3)return linePath(p);
  const dx=[],m=[],t=[];
  for(let i=0;i<n-1;i++){dx[i]=p[i+1][0]-p[i][0];m[i]=(p[i+1][1]-p[i][1])/(dx[i]||1e-9);}
  t[0]=m[0];t[n-1]=m[n-2];
  for(let i=1;i<n-1;i++)t[i]=m[i-1]*m[i]<=0?0:(m[i-1]+m[i])/2;
  for(let i=0;i<n-1;i++){if(m[i]===0){t[i]=0;t[i+1]=0;continue;}const a=t[i]/m[i],b=t[i+1]/m[i],s=a*a+b*b;if(s>9){const k=3/Math.sqrt(s);t[i]=k*a*m[i];t[i+1]=k*b*m[i];}}
  let d='M'+n1(p[0][0])+','+n1(p[0][1]);
  for(let i=0;i<n-1;i++){const h=dx[i]/3;d+=`C${n1(p[i][0]+h)},${n1(p[i][1]+h*t[i])} ${n1(p[i+1][0]-h)},${n1(p[i+1][1]-h*t[i+1])} ${n1(p[i+1][0])},${n1(p[i+1][1])}`;}
  return d;
}
function stepPath(p){let d='M'+n1(p[0][0])+','+n1(p[0][1]);for(let i=1;i<p.length;i++){const xm=n1((p[i-1][0]+p[i][0])/2);d+=`H${xm}V${n1(p[i][1])}H${n1(p[i][0])}`;}return d;}
const curve=(p,c)=>c==='smooth'?monoPath(p):c==='step'?stepPath(p):linePath(p);
function legendSvg(items,x,y,maxW,fs){
  let s='',cx=x,cy=y;
  for(const it of items){
    const w=TW(it.n,fs)+fs+16;
    if(cx+w>x+maxW&&cx>x){cx=x;cy+=fs+6;}
    const my=n1(cy-fs*.36);
    if(it.t==='line')s+=`<line x1="${n1(cx)}" y1="${my}" x2="${n1(cx+12)}" y2="${my}" stroke-width="2.5" stroke-linecap="round" style="stroke:${col(it.c)}"${it.dash?' stroke-dasharray="3 3"':''}/>`;
    else if(it.t==='dot')s+=`<circle cx="${n1(cx+5)}" cy="${my}" r="4" style="fill:${col(it.c)}"/>`;
    else s+=`<rect x="${n1(cx)}" y="${n1(my-4.5)}" width="9" height="9" rx="2" style="fill:${col(it.c)}"/>`;
    s+=`<text x="${n1(cx+(it.t==='line'?16:13))}" y="${n1(cy)}" class="lg">${esc(it.n)}</text>`;
    cx+=w;
  }
  return {s,h:items.length?cy-y+fs+8:0};
}
const tipA=(title,rows)=>esc([title,...rows.map(r=>r.join('~'))].join('|'));
const svgWrap=(W,H,fs,body,attrs,cls)=>`<svg class="v${cls?' '+cls:''}" viewBox="0 0 ${W} ${H}" font-size="${fs}" preserveAspectRatio="xMidYMid meet" ${attrs||''}>${body}</svg>`;
const FS=W=>W>=560?12:10;

/* ---------------- drill model (Power BI style) ----------------
   st.path : indices drilled into   st.lvl : absolute level shown
   st.exp  : "expand all down one level" (keeps parents)          */
function drillView(Hh,st){
  const path=st.path||[];let node=Hh.root;
  for(const p of path)node=node.c[p];
  const lvl=Math.max(st.lvl||1,path.length+1),rel=lvl-path.length;
  const cats=[],vals=[],drillable=[];let grp=null;
  if(rel===1){node.c.forEach(ch=>{cats.push(ch.n);vals.push(agg(ch));drillable.push(!!ch.c);});}
  else{
    const items=[];
    const walk=(n,d,anc)=>{if(d===rel){items.push({n,anc});return;}(n.c||[]).forEach(ch=>walk(ch,d+1,[...anc,n.n]));};
    node.c.forEach(ch=>walk(ch,1,[]));
    if(st.exp){grp=[];items.forEach(it=>{cats.push(it.n.n);vals.push(agg(it.n));grp.push(it.anc.join(' · '));drillable.push(false);});}
    else{const m=new Map();items.forEach(it=>{const k=it.n.n;if(!m.has(k))m.set(k,agg(it.n).slice());else{const a=m.get(k);agg(it.n).forEach((v,i)=>{a[i]+=v;});}});m.forEach((v,k)=>{cats.push(k);vals.push(v);drillable.push(false);});}
  }
  const crumb=[];let nd=Hh.root;for(const p of path){nd=nd.c[p];crumb.push(nd.n);}
  return {cats,vals,grp,drillable,rel,lvl,max:Hh.levels.length,crumb,level:Hh.levels[lvl-1],levels:Hh.levels,path};
}
function resolve(o,st){
  if(o.drill){const dv=drillView(o.drill,st||{});return {cats:dv.cats,grp:dv.grp,get:s=>dv.vals.map(r=>r[s.k||0]),dv};}
  return {cats:o.cats,grp:o.grp||null,get:s=>s.v,dv:null};
}

/* ======================= Cartesian ======================= */
function cartInner(o,st,fr,opt){
  opt=opt||{};st=st||{};
  const fs=opt.fs||10,V=(o.dir||'v')==='v',u=o.u||'',u2=o.u2||'';
  const R=resolve(o,st);
  const layers=o.layers.map(L=>({...L,mode:L.mode||(L.t==='bar'?'cluster':'line'),s:L.s.map((s,k)=>({...s,v:R.get(s),c:s.c==null?k+1:s.c}))}));
  let idx=[...Array(R.cats.length).keys()];
  if(o.sort){const L0=layers[0];const tot=i=>L0.s.reduce((a,s)=>a+(s.v[i]||0),0);idx.sort((a,b)=>o.sort==='asc'?tot(a)-tot(b):tot(b)-tot(a));}
  if(o.top)idx=idx.slice(0,o.top);
  const NN=idx.length;let z0=0;
  if(st.z){const a=Math.max(0,Math.floor(st.z[0]*NN+1e-6));const b=Math.min(NN,Math.max(a+2,Math.ceil(st.z[1]*NN-1e-6)));z0=a;idx=idx.slice(a,b);}
  const n=idx.length;
  /* domains */
  const A1={lo:Infinity,hi:-Infinity},A2={lo:Infinity,hi:-Infinity};let has2=false,pct1=false,pct2=false;
  const ext=(A,v)=>{if(v==null||isNaN(v))return;if(v<A.lo)A.lo=v;if(v>A.hi)A.hi=v;};
  for(const L of layers){
    const A=L.y2?A2:A1;if(L.y2)has2=true;
    if(L.mode==='pct'||L.area==='pct'){ext(A,0);ext(A,1);if(L.y2)pct2=true;else pct1=true;continue;}
    if(L.mode==='stack'||L.area==='stack'){for(const i of idx){let p=0,q=0;for(const s of L.s){const v=s.v[i]||0;if(v>=0)p+=v;else q+=v;}ext(A,p);ext(A,q);}ext(A,0);continue;}
    for(const s of L.s)for(const i of idx){ext(A,s.v[i]);if(s.f)ext(A,s.f[i]);if(s.lo){ext(A,s.lo[i]);ext(A,s.hi[i]);}if(s.elo){ext(A,s.elo[i]);ext(A,s.ehi[i]);}}
    if(L.t==='bar'||L.area||o.zero!==false)ext(A,0);
  }
  if(o.err)for(const i of idx){ext(A1,o.err.lo&&o.err.lo[i]);ext(A1,o.err.hi&&o.err.hi[i]);if(o.err.t)ext(A1,o.err.t[i]);}
  for(const r of(o.ref||[]))if(typeof r.v==='number'&&r.x==null)ext(r.y2?A2:A1,r.v);
  const lab1=layers.some(L=>!L.y2&&((L.t==='bar'&&(L.labels==='out'||(L.labels&&L.mode==='cluster')||L.total))||(L.t==='line'&&L.labels)));
  const stagger=layers.some(L=>L.t==='bar'&&L.mode==='cluster'&&L.labels&&L.s.length>1);
  if(lab1&&A1.hi>0&&!opt.yDom)A1.hi+=(A1.hi-Math.min(0,A1.lo))*(stagger?.16:.09);
  if(layers.some(L=>L.y2&&L.labels)&&A2.hi>0)A2.hi+=(A2.hi-Math.min(0,A2.lo))*.12;
  if(opt.yDom){ext(A1,opt.yDom[0]);ext(A1,opt.yDom[1]);}
  if(A1.lo===Infinity){A1.lo=0;A1.hi=1;}
  /* legend */
  const items=[];
  if(opt.legend!==false&&o.legend!==false){for(const L of layers)for(const s of L.s){if(s.nl)continue;items.push({n:s.n,c:s.c,t:L.t==='line'&&L.area!=='stack'&&L.area!=='pct'?'line':'rect',dash:s.dash});}if(o.legItems)items.push(...o.legItems);}
  let lg={s:'',h:0};
  if((items.length>1||o.legend===true)&&!o.endLabels)lg=legendSvg(items,fr.x+2,fr.y+fs+1,fr.w-4,fs);
  const D3=E.look==='3d'?(fs>=12?10:6):0;
  const top=fr.y+(lg.h?lg.h+2:6)+(layers.some(L=>L.t==='bar')?D3*.62:0);
  const plotHg=fr.h-(top-fr.y)-fs*2.4;
  const nt=V?Math.max(2,Math.min(6,Math.round(plotHg/(fs*4.2)))):Math.max(2,Math.min(6,Math.round(fr.w/(fs*9))));
  const T1=pct1?{lo:0,hi:1,t:[0,.25,.5,.75,1]}:ticks(A1.lo,A1.hi,nt);
  const T2=has2?(pct2?{lo:0,hi:1,t:[0,.25,.5,.75,1]}:ticks(A2.lo,A2.hi,T1.t.length-1)):null;
  const ylab=t=>pct1?Math.round(t*100)+'%':fmt(t,u);
  const y2lab=t=>pct2?Math.round(t*100)+'%':fmt(t,u2);
  const grp=R.grp&&V?idx.map(i=>R.grp[i]):null;
  const catLab=idx.map(i=>(R.grp&&!V)?R.grp[i]+' '+R.cats[i]:String(R.cats[i]));
  let left,right,bottom;
  if(V){
    const yw=opt.showY===false?0:Math.max(...T1.t.map(t=>TW(ylab(t),fs)))+8;
    left=fr.x+yw+2;
    let rp=8;
    if(has2)rp=Math.max(rp,Math.max(...T2.t.map(t=>TW(y2lab(t),fs)))+10);
    if(o.endLabels)rp=Math.max(rp,Math.min(fr.w*.3,Math.max(...items.map(it=>TW(it.n,fs))))+22);
    right=fr.x+fr.w-rp-(layers.some(L=>L.t==='bar')?D3:0);
    bottom=fr.y+fr.h-(opt.showX===false?3:fs+7)-(grp?fs+7:0);
  }else{
    const cw=Math.min(fr.w*.36,Math.max(...catLab.map(c=>TW(c,fs))))+8;
    left=fr.x+cw;
    const outLab=layers.some(L=>L.t==='bar'&&(L.labels==='out'||L.labels===true||L.total));
    right=fr.x+fr.w-Math.max(outLab?TW(fmt(A1.hi,u),fs)+12:10,TW(ylab(T1.t[T1.t.length-1]),fs)/2+4);
    bottom=fr.y+fr.h-(opt.showX===false?3:fs+7);
  }
  const pL=left,pR=right,pT=top,pB=bottom;
  const bw=(V?pR-pL:pB-pT)/n;
  const cp=j=>(V?pL:pT)+j*bw;
  const sc=(T,a0,a1)=>v=>a0+(v-T.lo)/((T.hi-T.lo)||1)*(a1-a0);
  const Y1=V?sc(T1,pB,pT):sc(T1,pL,pR);
  const Y2=has2?sc(T2,pB,pT):null;
  const base1=Y1(Math.max(T1.lo,Math.min(0,T1.hi)));
  let g='',mk='',ar='',ln='',dots='',lab='',over='',hov='';
  /* grid + value axis */
  for(const t of T1.t){const p=n1(Y1(t));
    if(V){g+=`<line class="gl" x1="${n1(pL)}" x2="${n1(pR)}" y1="${p}" y2="${p}"/>`;if(opt.showY!==false)g+=`<text x="${n1(pL-6)}" y="${n1(p+fs*.35)}" text-anchor="end" class="tk">${ylab(t)}</text>`;}
    else{g+=`<line class="gl" y1="${n1(pT)}" y2="${n1(pB)}" x1="${p}" x2="${p}"/>`;if(opt.showX!==false)g+=`<text x="${p}" y="${n1(pB+fs+4)}" text-anchor="middle" class="tk">${ylab(t)}</text>`;}
  }
  if(has2)for(const t of T2.t){const p=n1(Y2(t));g+=`<text x="${n1(pR+6)}" y="${n1(p+fs*.35)}" class="tk">${y2lab(t)}</text>`;}
  /* reference values */
  const s0=layers[0].s[0];const vis=idx.map(i=>s0.v[i]).filter(v=>v!=null);
  const refVal=r=>{if(typeof r.v==='number')return r.v;const a=[...vis].sort((x,y)=>x-y);if(r.v==='avg')return sumA(a)/a.length;if(r.v==='min')return a[0];if(r.v==='max')return a[a.length-1];if(r.v==='med'){const m=a.length>>1;return a.length%2?a[m]:(a[m-1]+a[m])/2;}if(r.v==='p75')return a[Math.floor((a.length-1)*.75)];return 0;};
  for(const r of(o.ref||[])){if(!r.shade||r.x!=null)continue;const p=(r.y2?Y2:Y1)(refVal(r));
    if(V){const y=r.shade==='above'?pT:p,h=r.shade==='above'?p-pT:pB-p;g+=`<rect class="shade" x="${n1(pL)}" y="${n1(y)}" width="${n1(pR-pL)}" height="${n1(Math.max(0,h))}"/>`;}
    else{const x=r.shade==='above'?p:pL,w=r.shade==='above'?pR-p:p-pL;g+=`<rect class="shade" y="${n1(pT)}" x="${n1(x)}" height="${n1(pB-pT)}" width="${n1(Math.max(0,w))}"/>`;}}
  if(T1.lo<=0&&T1.hi>=0){const p=n1(base1);g+=V?`<line class="bl" x1="${n1(pL)}" x2="${n1(pR)}" y1="${p}" y2="${p}"/>`:`<line class="bl" y1="${n1(pT)}" y2="${n1(pB)}" x1="${p}" x2="${p}"/>`;}
  /* bars */
  const cap=opt.cap||24;const cen={};let barW=0;
  const placed=[];const free=b=>!placed.some(q=>b[0]<q[2]&&b[2]>q[0]&&b[1]<q[3]&&b[3]>q[1]);
  const cb=o.colorBy;
  for(const L of layers.filter(L=>L.t==='bar')){
    const A=L.y2?Y2:Y1,b0=L.y2?Y2(Math.max(T2.lo,Math.min(0,T2.hi))):base1;
    if(L.mode==='cluster'){
      const ov=!!L.overlay,k=ov?1:L.s.length,gap=k>1?2:0;let w=o.hist?Math.max(1,bw-1.5):Math.min(cap,(bw*(k>1?.8:.64)-gap*(k-1))/k);w=Math.max(1.2,w);const gw=w*k+gap*(k-1);barW=w;
      let mn=Infinity,mx=-Infinity;if(cb&&cb.k==='grad')for(const i of idx){const v=L.s[0].v[i];if(v!=null){mn=Math.min(mn,v);mx=Math.max(mx,v);}}
      idx.forEach((i,j)=>{L.s.forEach((sr,si)=>{
        const v=sr.v[i];if(v==null)return;
        const c0=cp(j)+(bw-gw)/2+(ov?0:si*(w+gap)),p=A(v);
        if(si===0)cen[i]=c0+w/2;
        let ct=sr.c;
        if(cb&&L.s.length===1){if(cb.k==='rule')ct=cb.f(v,i);else if(cb.k==='hl')ct=i===cb.i?sr.c:'muted-mark';else if(cb.k==='cat')ct=i%8+1;else if(cb.k==='grad')ct='s'+(3+Math.round((v-mn)/((mx-mn)||1)*4));}
        const dl=`animation-delay:${Math.min(j*22,480)}ms${ov?';fill-opacity:.62':''}`;
        if(D3&&!ov)mk+=prism(V?c0:Math.min(p,b0),V?Math.min(p,b0):c0,V?w:Math.abs(p-b0),V?Math.abs(p-b0):w,ct,`m pr${V?'':' mh'}${v<0?' neg':''}`,i,dl,V,D3);
        else{const d=V?bp(c0,Math.min(p,b0),w,Math.abs(p-b0),o.hist?1:3.5,v>=0?'t':'b'):bp(Math.min(p,b0),c0,Math.abs(p-b0),w,3.5,v>=0?'r':'l');
          mk+=`<path class="m${V?'':' mh'}${v<0?' neg':''}${kc(ct)}" data-i="${i}" d="${d}" style="fill:${col(ct)};${dl}"/>`;}
        if(L.labels){const t=fmt(v,L.y2?u2:u),tw=TW(t,fs);
          if(V){const inside=L.labels==='in'&&Math.abs(p-b0)>fs+8&&w>=tw+4;const cx=c0+w/2;
            if(inside)lab+=`<text x="${n1(cx)}" y="${n1(v>=0?p+fs+3:p-5)}" text-anchor="middle" class="li${ki(ct)}">${t}</text>`;
            else if(!ov&&(k===1?tw<=bw-2:tw<=2.2*(w+gap))){let y=v>=0?p-4-D3*.62:p+fs+3;let b=[cx-tw/2-1,y-fs,cx+tw/2+1,y+2];
              for(let tries=0;tries<3&&!free(b);tries++){const hit=placed.filter(q=>b[0]<q[2]&&b[2]>q[0]&&b[1]<q[3]&&b[3]>q[1]);y=Math.min(...hit.map(q=>q[1]))-2;b=[cx-tw/2-1,y-fs,cx+tw/2+1,y+2];}
              if(free(b)&&y-fs>=pT-4){placed.push(b);lab+=`<text x="${n1(cx)}" y="${n1(y)}" text-anchor="middle" class="lb">${t}</text>`;}}}
          else{const inside=L.labels==='in'&&Math.abs(p-b0)>tw+10&&w>=fs+2;lab+=`<text x="${n1(inside?(v>=0?p-5:p+5):(v>=0?p+5+D3:p-5))}" y="${n1(c0+w/2+fs*.36)}" text-anchor="${inside===(v>=0)?'end':'start'}" class="${inside?'li'+ki(ct):'lb'}">${t}</text>`;}}
      });});
    }else{
      const w=Math.min(cap+6,bw*.62);barW=w;
      idx.forEach((i,j)=>{
        let tot=0;L.s.forEach(sr=>{tot+=Math.abs(sr.v[i]||0);});
        let pp=0,qq=0;const c0=cp(j)+(bw-w)/2;cen[i]=c0+w/2;const segs=[];
        L.s.forEach((sr,si)=>{let v=sr.v[i];if(v==null||v===0)return;const raw=v;if(L.mode==='pct')v=v/(tot||1);const a=v>=0?pp:qq,b=a+v;if(v>=0)pp=b;else qq=b;segs.push({si,v,a,b,raw});});
        const lp=segs.filter(s=>s.v>0).pop(),lq=segs.filter(s=>s.v<0).pop();
        segs.forEach(sg=>{
          let pa=A(sg.a),pb=A(sg.b);const dir=pb>pa?1:-1;const isEnd=sg===lp||sg===lq;
          if(sg.a!==0)pa+=dir*1;if(!isEnd)pb-=dir*1;
          const sr=L.s[sg.si];let ct=sr.c;if(cb&&cb.k==='hls')ct=sg.si===cb.i?sr.c:'muted-mark';
          const len=Math.abs(pb-pa);const dl=`animation-delay:${Math.min(j*22,480)}ms`;
          if(D3)mk+=prism(V?c0:Math.min(pa,pb),V?Math.min(pa,pb):c0,V?w:len,V?len:w,ct,`m pr${V?'':' mh'}`,i,dl,V,D3);
          else{const d=V?bp(c0,Math.min(pa,pb),w,len,3.5,isEnd?(sg.v>=0?'t':'b'):'none'):bp(Math.min(pa,pb),c0,len,w,3.5,isEnd?(sg.v>=0?'r':'l'):'none');
            mk+=`<path class="m${V?'':' mh'}${kc(ct)}" data-i="${i}" d="${d}" style="fill:${col(ct)};${dl}"/>`;}
          if(L.labels){const t=L.mode==='pct'?Math.round(Math.abs(sg.v)*100)+'%':fmt(sg.raw,u),tw=TW(t,fs);
            const fits=V?(len>fs+3&&w>=tw+3):(len>=tw+6&&w>=fs+1);
            if(fits){const cx=V?c0+w/2:(pa+pb)/2,cy=V?(pa+pb)/2+fs*.36:c0+w/2+fs*.36;lab+=`<text x="${n1(cx)}" y="${n1(cy)}" text-anchor="middle" class="li${ki(ct)}">${t}</text>`;}}
        });
        if(L.total&&L.mode!=='pct'){const t=fmt(pp+qq,u),p=A(pp);lab+=V?`<text x="${n1(c0+w/2)}" y="${n1(p-5-D3*.62)}" text-anchor="middle" class="lb lbt">${t}</text>`:`<text x="${n1(p+5+D3)}" y="${n1(c0+w/2+fs*.36)}" class="lb lbt">${t}</text>`;}
      });
    }
  }
  /* lines and areas */
  const hp={};const ends=[];
  for(const L of layers.filter(L=>L.t==='line')){
    const A=L.y2?Y2:Y1;const cum=(L.area==='stack'||L.area==='pct')?idx.map(()=>0):null;
    const tots=L.area==='pct'?idx.map(i=>L.s.reduce((a,s)=>a+(s.v[i]||0),0)):null;
    const zeroY=A(Math.max((L.y2?T2:T1).lo,Math.min(0,(L.y2?T2:T1).hi)));
    L.s.forEach((sr,si)=>{
      const pts=[],bas=[];
      idx.forEach((i,j)=>{let v=sr.v[i];if(v==null){pts.push(null);bas.push(null);return;}if(tots)v=v/(tots[j]||1);const x=cp(j)+bw/2;let b=0;if(cum){b=cum[j];cum[j]+=v;}const y=A(b+v);pts.push([x,y]);bas.push([x,A(b)]);(hp[i]=hp[i]||[]).push([x,y,sr.c]);});
      const segs=[];let cur=null;pts.forEach((p,j)=>{if(p){if(!cur){cur={p:[],b:[]};segs.push(cur);}cur.p.push(p);cur.b.push(bas[j]);}else cur=null;});
      const stroke=cb&&cb.k==='focus'?(si===cb.i?col(sr.c):'var(--muted-mark)'):col(sr.c);const stok=cb&&cb.k==='focus'&&si!==cb.i?'muted-mark':sr.c;
      segs.forEach(sg=>{
        if(L.area){const topP=curve(sg.p,L.curve);const bot=cum?curve(sg.b.slice().reverse(),L.curve).replace(/^M/,'L'):`L${n1(sg.p[sg.p.length-1][0])},${n1(zeroY)}L${n1(sg.p[0][0])},${n1(zeroY)}`;
          ar+=`<path class="ar${cum?' ars':''}${kc(stok)}" d="${topP}${bot}Z" style="fill:${stroke};fill-opacity:${cum?.5:(L.fo||.13)}"/>`;}
        if(sg.p.length>1||!L.area)ln+=`<path class="ln" d="${curve(sg.p,L.curve)}"${sr.dash?' stroke-dasharray="5 4"':' pathLength="1"'} style="stroke:${stroke};stroke-width:${L.w||2}"/>`;
      });
      const valid=pts.map((p,j)=>p?j:-1).filter(j=>j>=0);const lastJ=valid[valid.length-1];
      if(L.mk&&!(cb&&cb.k==='focus'&&si!==cb.i))pts.forEach((p,j)=>{if(!p||(L.mk==='end'&&j!==lastJ))return;dots+=`<circle class="mk" data-i="${idx[j]}" cx="${n1(p[0])}" cy="${n1(p[1])}" r="${L.mk==='big'?4.5:3.5}" style="fill:${stroke}"/>`;});
      if(L.labels&&!(cb&&cb.k==='focus'&&si!==cb.i)){
        let show=[];if(L.labels==='end')show=[lastJ];else if(L.labels==='minmax'){let a=valid[0],b=valid[0];valid.forEach(j=>{if(sr.v[idx[j]]>sr.v[idx[a]])a=j;if(sr.v[idx[j]]<sr.v[idx[b]])b=j;});show=[a,b];dots+=[a,b].map(j=>`<circle class="mk" cx="${n1(pts[j][0])}" cy="${n1(pts[j][1])}" r="4" style="fill:${stroke}"/>`).join('');}else show=valid.length<=14?valid:valid.filter((j,k)=>k%2===0);
        show.forEach(j=>{const p=pts[j];if(!p)return;let v=sr.v[idx[j]];if(tots)v=v/(tots[j]||1);const t=tots?Math.round(v*100)+'%':fmt(v,L.y2?u2:u);const tw=TW(t,fs);
          const cands=L.labels==='minmax'&&j===show[1]?[p[1]+fs+5,p[1]-7]:[p[1]-7,p[1]+fs+5];
          for(const y of cands){let x=p[0];x=Math.max(pL+tw/2,Math.min(pR-tw/2+4,x));const b=[x-tw/2-1,y-fs,x+tw/2+1,y+2];if(y-fs<pT-2)continue;if(free(b)){placed.push(b);lab+=`<text x="${n1(x)}" y="${n1(y)}" text-anchor="middle" class="lb">${t}</text>`;break;}}});
      }
      if(sr.f){
        const fi=idx.map((i,j)=>sr.f[i]==null?null:j).filter(j=>j!=null);
        if(fi.length){const fp=fi.map(j=>[cp(j)+bw/2,A(sr.f[idx[j]])]);
          if(sr.lo){const up=fi.map(j=>[cp(j)+bw/2,A(sr.hi[idx[j]])]),dn=fi.map(j=>[cp(j)+bw/2,A(sr.lo[idx[j]])]).reverse();ar+=`<path class="ci" d="${linePath(up)}${linePath(dn).replace(/^M/,'L')}Z" style="fill:${stroke}"/>`;}
          ln+=`<path class="ln" d="${linePath(fp)}" stroke-dasharray="4 3" style="stroke:${stroke};stroke-width:2"/>`;
          fi.forEach(j=>{(hp[idx[j]]=hp[idx[j]]||[]).push([cp(j)+bw/2,A(sr.f[idx[j]]),sr.c]);});}
      }
      if(sr.elo){const up=idx.map((i,j)=>[cp(j)+bw/2,A(sr.ehi[i])]),dn=idx.map((i,j)=>[cp(j)+bw/2,A(sr.elo[i])]).reverse();ar+=`<path class="ci" d="${linePath(up)}${linePath(dn).replace(/^M/,'L')}Z" style="fill:${stroke}"/>`;}
      if(sr.anom)idx.forEach((i,j)=>{if(!sr.anom.includes(i)||!pts[j])return;dots+=`<circle class="an" cx="${n1(pts[j][0])}" cy="${n1(pts[j][1])}" r="8"/><circle class="mk" cx="${n1(pts[j][0])}" cy="${n1(pts[j][1])}" r="4.5" style="fill:var(--crit)"/>`;});
      if(L.trend&&si===0&&valid.length>2){const X=valid.map(j=>j),Yv=valid.map(j=>sr.v[idx[j]]);const mx=sumA(X)/X.length,my=sumA(Yv)/Yv.length;let a=0,b=0;X.forEach((x,k)=>{a+=(x-mx)*(Yv[k]-my);b+=(x-mx)*(x-mx);});const sl=a/(b||1),ic=my-sl*mx;const j0=valid[0],j1=lastJ;over+=`<line class="tr" x1="${n1(cp(j0)+bw/2)}" y1="${n1(A(ic+sl*j0))}" x2="${n1(cp(j1)+bw/2)}" y2="${n1(A(ic+sl*j1))}"/>`;}
      if(lastJ!=null&&pts[lastJ])ends.push({x:pts[lastJ][0],y:pts[lastJ][1],n:sr.n,c:sr.c});
    });
  }
  /* error bars / target markers */
  if(o.err){const e=o.err;
    if(e.style==='band'){const up=idx.map((i,j)=>[cp(j)+bw/2,Y1(e.hi[i])]),dn=idx.map((i,j)=>[cp(j)+bw/2,Y1(e.lo[i])]).reverse();ar+=`<path class="ci" d="${linePath(up)}${linePath(dn).replace(/^M/,'L')}Z" style="fill:var(--c1)"/>`;}
    else idx.forEach((i,j)=>{const c=cen[i]!=null?cen[i]:cp(j)+bw/2;
      if(e.style==='marker'){const p=n1(Y1(e.t[i]));const h=Math.max(barW,6)/2+4;over+=V?`<line class="tgt" x1="${n1(c-h)}" x2="${n1(c+h)}" y1="${p}" y2="${p}"/>`:`<line class="tgt" y1="${n1(c-h)}" y2="${n1(c+h)}" x1="${p}" x2="${p}"/>`;}
      else{const a=n1(Y1(e.lo[i])),b=n1(Y1(e.hi[i]));over+=V?`<path class="eb" d="M${n1(c)},${a}V${b}M${n1(c-4)},${a}h8M${n1(c-4)},${b}h8"/>`:`<path class="eb" d="M${a},${n1(c)}H${b}M${a},${n1(c-4)}v8M${b},${n1(c-4)}v8"/>`;}});
  }
  /* reference lines */
  for(const r of(o.ref||[])){
    if(r.x!=null){const j=idx.indexOf(r.x);if(j<0)continue;const x=n1(cp(j)+bw/2);over+=`<line class="ref" x1="${x}" x2="${x}" y1="${n1(pT)}" y2="${n1(pB)}"/><text class="reft" x="${n1(x+4)}" y="${n1(pT+fs)}">${esc(r.n)}</text>`;continue;}
    if(r.shade&&!r.line)continue;
    const v=refVal(r),p=n1((r.y2?Y2:Y1)(v)),lb=(r.n?r.n+' ':'')+(r.nv?'':((pct1&&!r.y2)?Math.round(v*100)+'%':fmt(v,r.y2?u2:u)));
    const sty=r.c?` style="stroke:${col(r.c)}"`:'';
    if(V)over+=`<line class="ref" x1="${n1(pL)}" x2="${n1(pR)}" y1="${p}" y2="${p}"${sty}/><text class="reft" x="${n1(pR-3)}" y="${n1(p-4)}" text-anchor="end">${esc(lb)}</text>`;
    else over+=`<line class="ref" y1="${n1(pT)}" y2="${n1(pB)}" x1="${p}" x2="${p}"${sty}/><text class="reft" x="${n1(p+4)}" y="${n1(pT+fs)}">${esc(lb)}</text>`;
  }
  /* series end labels (instead of legend) */
  if(o.endLabels&&ends.length){
    const ord=ends.slice().sort((a,b)=>a.y-b.y);const gapY=fs+3;
    for(let k=1;k<ord.length;k++)ord[k].ly=Math.max(ord[k].y,(ord[k-1].ly??ord[k-1].y)+gapY);
    ord[0].ly=ord[0].ly??ord[0].y;
    const over2=(ord[ord.length-1].ly)-(pB);if(over2>0)ord.forEach(e=>{e.ly-=over2;});
    ord.forEach(e=>{const lx=pR+6;over+=`<path class="lead" d="M${n1(e.x+4)},${n1(e.y)}L${n1(lx)},${n1(e.ly)}"/><line x1="${n1(lx+1)}" x2="${n1(lx+9)}" y1="${n1(e.ly)}" y2="${n1(e.ly)}" stroke-width="2.5" stroke-linecap="round" style="stroke:${col(e.c)}"/><text class="lg" x="${n1(lx+12)}" y="${n1(e.ly+fs*.36)}">${esc(trunc(e.n,fr.x+fr.w-lx-14,fs))}</text>`;});
  }
  /* category axis */
  if(V){
    if(opt.showX!==false){
      const maxW=Math.max(...catLab.map(c=>TW(c,fs)));const step=Math.max(1,Math.ceil((maxW+6)/bw));
      idx.forEach((i,j)=>{if(j%step)return;g+=`<text x="${n1(cp(j)+bw/2)}" y="${n1(pB+fs+4)}" text-anchor="middle" class="tk">${esc(trunc(catLab[j],bw*step-4,fs))}</text>`;});
      if(grp){let a=0;for(let j=1;j<=n;j++){if(j===n||grp[j]!==grp[a]){const x0=cp(a),x1=cp(j);g+=`<text x="${n1((x0+x1)/2)}" y="${n1(pB+fs*2+9)}" text-anchor="middle" class="tk2">${esc(trunc(grp[a],x1-x0-4,fs))}</text>`;if(a>0)g+=`<line class="gl" x1="${n1(x0)}" x2="${n1(x0)}" y1="${n1(pB+2)}" y2="${n1(pB+fs*2+11)}"/>`;a=j;}}}
    }
  }else{
    const step=Math.max(1,Math.ceil((fs+2)/bw));
    idx.forEach((i,j)=>{if(j%step)return;g+=`<text x="${n1(pL-6)}" y="${n1(cp(j)+bw/2+fs*.36)}" text-anchor="end" class="tk">${esc(trunc(catLab[j],pL-fr.x-8,fs))}</text>`;});
  }
  /* hover / hit layer: one tooltip lists every series at that category */
  const hasLine=layers.some(L=>L.t==='line');
  idx.forEach((i,j)=>{
    const rows=[];
    for(const L of layers){const tot=(L.mode==='pct'||L.area==='pct')?L.s.reduce((a,s)=>a+Math.abs(s.v[i]||0),0):0;
      for(const sr of L.s){let v=sr.v[i];if(v==null&&sr.f&&sr.f[i]!=null){rows.push([fmt(sr.f[i],L.y2?u2:u),sr.n+' (forecast)',sr.c]);continue;}if(v==null)continue;rows.push([fmt(v,L.y2?u2:u)+(tot?` · ${Math.round(Math.abs(v)/tot*100)}%`:''),sr.n,sr.c]);}}
    if(o.err&&o.err.lo)rows.push([fmt(o.err.lo[i],u)+' – '+fmt(o.err.hi[i],u),'Range','muted']);
    if(o.err&&o.err.t)rows.push([fmt(o.err.t[i],u),'Target','ink']);
    const title=(R.grp&&R.grp[i]?R.grp[i]+' · ':'')+R.cats[i];
    const dr=R.dv&&R.dv.rel===1&&R.dv.drillable[i]&&R.dv.lvl<R.dv.max?` data-d="${i}"`:'';
    const hit=V?`x="${n1(cp(j))}" y="${n1(pT)}" width="${n1(bw)}" height="${n1(pB-pT)}"`:`x="${n1(pL)}" y="${n1(cp(j))}" width="${n1(pR-pL)}" height="${n1(bw)}"`;
    let ex='';
    if(hasLine&&V){const x=n1(cp(j)+bw/2);ex+=`<line class="xh" x1="${x}" x2="${x}" y1="${n1(pT)}" y2="${n1(pB)}"/>`;(hp[i]||[]).forEach(q=>{ex+=`<circle class="hd" cx="${n1(q[0])}" cy="${n1(q[1])}" r="4.5" style="fill:${col(q[2])}"/>`;});}
    hov+=`<g class="cg" data-i="${i}" data-t="${tipA(title,rows)}"${dr}><rect class="hit" ${hit}/>${ex}</g>`;
  });
  const body=g+`<g class="gm">${mk}</g>`+ar+ln+dots+lab+over+hov+lg.s;
  return {s:body,plot:{l:pL,r:pR,t:pT,b:pB,n,z0,nn:NN},dv:R.dv};
}
E.cart={draw(o,st,W,H){const fs=FS(W);const r=cartInner(o,st,{x:0,y:0,w:W,h:H},{fs,cap:W>=560?32:22});
  return svgWrap(W,H,fs,r.s,`data-pl="${n1(r.plot.l)}" data-pr="${n1(r.plot.r)}" data-pt="${n1(r.plot.t)}" data-pb="${n1(r.plot.b)}" data-n="${r.plot.n}" data-z0="${r.plot.z0}" data-nn="${r.plot.nn}"`);}};

/* small multiples: shared y scale, shared legend */
E.sm={draw(o,st,W,H){
  const fs=FS(W),P=o.panels,n=P.length,cols=o.cols||(n<=2?n:n<=4?2:3),rows=Math.ceil(n/cols);
  let lo=0,hi=0;
  P.forEach(p=>p.layers.forEach(L=>{const len=L.s[0].v.length;for(let i=0;i<len;i++){if(L.mode==='stack'||L.area==='stack'){let a=0;L.s.forEach(s=>{a+=s.v[i]||0;});hi=Math.max(hi,a);}else L.s.forEach(s=>{hi=Math.max(hi,s.v[i]||0);lo=Math.min(lo,s.v[i]||0);});}}));
  const pct=P[0].layers.some(L=>L.mode==='pct'||L.area==='pct');
  const items=P[0].layers.flatMap(L=>L.s.map((s,k)=>({n:s.n,c:s.c==null?k+1:s.c,t:L.t==='line'&&!L.area?'line':'rect',dash:s.dash})));
  const lg=items.length>1?legendSvg(items,2,fs+1,W-4,fs):{s:'',h:0};
  const gx=10,gy=6,top=lg.h?lg.h+2:2;const gw=(W-(cols-1)*gx)/cols,gh=(H-top-(rows-1)*gy)/rows;
  let s=lg.s;
  P.forEach((p,j)=>{const x=(j%cols)*(gw+gx),y=top+Math.floor(j/cols)*(gh+gy);
    s+=`<text x="${n1(x+2)}" y="${n1(y+fs)}" class="smt">${esc(p.n)}</text>`;
    const r=cartInner({...o,...p,layers:p.layers,legend:false},{},{x,y:y+fs+2,w:gw,h:gh-fs-2},{fs:fs-1,legend:false,yDom:pct?null:[lo,hi],showY:j%cols===0,showX:Math.floor(j/cols)===rows-1||j+cols>=n,cap:W>=560?20:12});
    s+=`<g class="pn">${r.s}</g>`;});
  return svgWrap(W,H,fs,s);
}};

/* ======================= Ribbon ======================= */
E.ribbon={draw(o,st,W,H){
  const fs=FS(W),cats=o.cats,S=o.s,n=cats.length,k=S.length;
  const lg=legendSvg(S.map((s,i)=>({n:s,c:i+1})),2,fs+1,W-4,fs);
  const top=lg.h+4,bot=H-fs-8,L=6,R=W-6,bw=(R-L)/n,cw=Math.min(bw*.44,W>=560?34:22);
  const tots=cats.map((_,p)=>sumA(o.v.map(v=>v[p])));const mx=Math.max(...tots);const gap=2;
  const sc=(bot-top-gap*k)/mx;const pos=[];let mk='',rb='',lab='',hov='';
  cats.forEach((c,p)=>{const ord=S.map((_,i)=>i).sort((a,b)=>o.v[a][p]-o.v[b][p]);let y=bot;const x0=L+p*bw+(bw-cw)/2;pos[p]=[];
    ord.forEach((si,rank)=>{const h=o.v[si][p]*sc;pos[p][si]={x0,x1:x0+cw,y0:y-h,y1:y,rank:k-rank};y-=h+gap;});});
  for(let p=0;p<n-1;p++)S.forEach((s,si)=>{const a=pos[p][si],b=pos[p+1][si],xm=(a.x1+b.x0)/2;
    rb+=`<path class="rbn${kc(si+1)}" data-i="${si}" d="M${n1(a.x1)},${n1(a.y0)}C${n1(xm)},${n1(a.y0)} ${n1(xm)},${n1(b.y0)} ${n1(b.x0)},${n1(b.y0)}L${n1(b.x0)},${n1(b.y1)}C${n1(xm)},${n1(b.y1)} ${n1(xm)},${n1(a.y1)} ${n1(a.x1)},${n1(a.y1)}Z" style="fill:${col(si+1)};fill-opacity:${o.op||.32}"/>`;});
  cats.forEach((c,p)=>{S.forEach((s,si)=>{const q=pos[p][si];
    mk+=`<path class="m${kc(si+1)}" data-i="${si}" d="${bp(q.x0,q.y0,cw,q.y1-q.y0,2,'none')}" style="fill:${col(si+1)};animation-delay:${p*40}ms"/>`;
    if(o.labels&&q.y1-q.y0>fs+3&&cw>=TW(fmt(o.v[si][p]),fs-1)+2)lab+=`<text x="${n1(q.x0+cw/2)}" y="${n1((q.y0+q.y1)/2+fs*.33)}" text-anchor="middle" class="li${ki(si+1)}" font-size="${fs-1}">${fmt(o.v[si][p],o.u)}</text>`;
    hov+=`<rect class="hit" data-i="${si}" x="${n1(q.x0-2)}" y="${n1(q.y0)}" width="${n1(cw+4)}" height="${n1(Math.max(4,q.y1-q.y0))}" data-t="${tipA(c+' · '+s,[[fmt(o.v[si][p],o.u),'Value',si+1],['#'+q.rank+' of '+k,'Rank','muted']])}"/>`;});
    lab+=`<text x="${n1(L+p*bw+bw/2)}" y="${n1(bot+fs+4)}" text-anchor="middle" class="tk">${esc(trunc(c,bw-2,fs))}</text>`;});
  return svgWrap(W,H,fs,`<line class="bl" x1="${L}" x2="${R}" y1="${n1(bot+.5)}" y2="${n1(bot+.5)}"/>`+rb+`<g class="gm">${mk}</g>`+lab+hov+lg.s);
}};

/* ======================= Waterfall ======================= */
E.wfall={draw(o,st,W,H){
  const fs=FS(W),u=o.u||'$';let cur=0;const arr=[];
  for(const s of o.steps){if(s.t){const v=s.v!=null?s.v:cur;arr.push({n:s.n,a:0,b:v,k:'tot',v});cur=v;}else{arr.push({n:s.n,a:cur,b:cur+s.v,k:s.v>=0?'inc':'dec',v:s.v});cur+=s.v;}}
  let lo=0,hi=0;arr.forEach(a=>{lo=Math.min(lo,a.a,a.b);hi=Math.max(hi,a.a,a.b);});
  if(o.ymin!=null)lo=o.ymin;
  const T=o.ymin!=null?{...ticks(lo,hi,4),lo:o.ymin}:ticks(lo,hi,4);if(o.ymin!=null)T.t=T.t.filter(t=>t>=o.ymin);
  const items=o.legend===false?[]:[{n:'Increase',c:'good'},{n:'Decrease',c:'crit'},{n:'Total',c:o.totc||1}];
  const lg=legendSvg(items,2,fs+1,W-4,fs);const top=lg.h+4+(E.look==='3d'?7:0);
  const yw=Math.max(...T.t.map(t=>TW(fmt(t,u),fs)))+8;const L=yw,R=W-6;const twoLine=arr.some(a=>TW(a.n,fs)>(R-L)/arr.length-2);
  const B=H-(twoLine?fs*2+9:fs+7);const n=arr.length,bw=(R-L)/n,w=Math.min(W>=560?40:26,bw*.66);
  const Y=v=>B-(v-T.lo)/((T.hi-T.lo)||1)*(B-top);
  let g='',mk='',lab='',hov='',cn='';
  T.t.forEach(t=>{g+=`<line class="gl" x1="${L}" x2="${R}" y1="${n1(Y(t))}" y2="${n1(Y(t))}"/><text x="${L-6}" y="${n1(Y(t)+fs*.35)}" text-anchor="end" class="tk">${fmt(t,u)}</text>`;});
  if(T.lo<0)g+=`<line class="bl" x1="${L}" x2="${R}" y1="${n1(Y(0))}" y2="${n1(Y(0))}"/>`;
  arr.forEach((a,j)=>{const x=L+j*bw+(bw-w)/2,y0=Y(Math.max(a.a,a.b)),y1=Y(Math.max(T.lo,Math.min(a.a,a.b)));
    const ct=a.k==='tot'?(o.totc||1):a.k==='inc'?'good':'crit',dl=`animation-delay:${j*45}ms`;
    mk+=E.look==='3d'?prism(x,y0,w,Math.max(1,y1-y0),ct,'m pr',j,dl,true,fs>=12?10:6):`<path class="m${kc(ct)}" data-i="${j}" d="${bp(x,y0,w,Math.max(1,y1-y0),2.5,'all')}" style="fill:${col(ct)};${dl}"/>`;
    if(j<n-1){const yy=n1(Y(a.b));cn+=`<line class="cn" x1="${n1(x+w)}" x2="${n1(L+(j+1)*bw+(bw-w)/2)}" y1="${yy}" y2="${yy}"/>`;}
    if(o.labels!==false){const t=a.k==='tot'?fmt(a.v,u):fmtS(a.v,u);lab+=`<text x="${n1(x+w/2)}" y="${n1(y0-4-(E.look==='3d'?5:0))}" text-anchor="middle" class="lb">${t}</text>`;}
    const cx=n1(L+j*bw+bw/2);
    if(twoLine&&a.n.includes(' ')){const sp=a.n.split(' '),h=Math.ceil(sp.length/2);g+=`<text x="${cx}" y="${n1(B+fs+4)}" text-anchor="middle" class="tk">${esc(trunc(sp.slice(0,h).join(' '),bw-2,fs))}</text><text x="${cx}" y="${n1(B+fs*2+6)}" text-anchor="middle" class="tk">${esc(trunc(sp.slice(h).join(' '),bw-2,fs))}</text>`;}
    else g+=`<text x="${cx}" y="${n1(B+fs+4)}" text-anchor="middle" class="tk">${esc(trunc(a.n,bw-2,fs))}</text>`;
    hov+=`<rect class="hit" data-i="${j}" x="${n1(L+j*bw)}" y="${top}" width="${n1(bw)}" height="${n1(B-top)}" data-t="${tipA(a.n,a.k==='tot'?[[fmt(a.v,u),'Total',o.totc||1]]:[[fmtS(a.v,u),a.k==='inc'?'Increase':'Decrease',a.k==='inc'?'good':'crit'],[fmt(a.b,u),'Running total','muted']])}"/>`;});
  return svgWrap(W,H,fs,g+cn+`<g class="gm">${mk}</g>`+lab+hov+lg.s);
}};

/* ======================= Funnel ======================= */
E.funnel={draw(o,st,W,H){
  const fs=FS(W),it=o.stages,n=it.length,first=it[0].v;
  const lw=Math.max(...it.map(s=>TW(s.n,fs)))+12;const top=6,bot=H-(o.conv?fs+12:6);
  const rh=(bot-top)/n,bh=Math.min(rh-4,W>=560?44:28);const pw=W-lw-10,cx=lw+pw/2;
  let s='',lab='',hov='';
  it.forEach((st_,i)=>{const w=Math.max(4,st_.v/first*pw),x=cx-w/2,y=top+i*rh+(rh-bh)/2;
    const ct=o.vary?i+1:o.grad?'s'+(7-Math.min(4,i)):1,dl=`animation-delay:${i*60}ms`;
    s+=E.look==='3d'?prism(x,y,w,bh,ct,'m mf pr',i,dl,true,fs>=12?9:6):`<path class="m mf${kc(ct)}" data-i="${i}" d="${bp(x,y,w,bh,3,'all')}" style="fill:${col(ct)};${dl}"/>`;
    let t=fmt(st_.v,o.u);if(o.pct==='first')t+=` · ${i?(st_.v/first*100).toFixed(1)+'%':'100%'}`;if(o.pct==='prev')t+=i?` · ${(st_.v/it[i-1].v*100).toFixed(1)}%`:'';
    const tw=TW(t,fs);const inside=w>=tw+10;
    lab+=`<text x="${n1(inside?cx:x+w+5+(E.look==='3d'?Math.min(9,bh*.55+1.5):0))}" y="${n1(y+bh/2+fs*.36)}" text-anchor="${inside?'middle':'start'}" class="${inside?'li'+ki(ct):'lb'}">${t}</text>`;
    lab+=`<text x="${n1(lw-8)}" y="${n1(y+bh/2+fs*.36)}" text-anchor="end" class="tk tkb">${esc(st_.n)}</text>`;
    hov+=`<rect class="hit" data-i="${i}" x="0" y="${n1(top+i*rh)}" width="${W}" height="${n1(rh)}" data-t="${tipA(st_.n,[[fmt(st_.v,o.u),'Count',1],[(st_.v/first*100).toFixed(1)+'%','% of first','muted'],[i?(st_.v/it[i-1].v*100).toFixed(1)+'%':'–','% of previous','muted']])}"/>`;});
  if(o.conv)lab+=`<text x="${n1(cx)}" y="${n1(H-4)}" text-anchor="middle" class="lb">Conversion rate ${(it[n-1].v/first*100).toFixed(1)}%</text>`;
  return svgWrap(W,H,fs,`<g class="gm">${s}</g>`+lab+hov);
}};

/* ======================= Pie & donut ======================= */
E.pie={draw(o,st,W,H){
  const fs=FS(W),R0=resolve(o.ring?{cats:[]}:o,st);
  let items=R0.cats.map((n,i)=>({n,v:R0.dv?R0.dv.vals[i][o.k||0]:o.v[i],i,d:R0.dv&&R0.dv.rel===1&&R0.dv.drillable[i]&&R0.dv.lvl<R0.dv.max}));
  if(o.sort!==false)items.sort((a,b)=>b.v-a.v);
  if(o.topN&&items.length>o.topN){const keep=items.slice(0,o.topN),rest=items.slice(o.topN);keep.push({n:'Other',v:sumA(rest.map(r=>r.v)),i:999,other:true});items=keep;}
  if(o.ring)items=[{n:o.ring[0],v:o.ring[1],i:0},{n:o.ring[2],v:o.ring[3],i:1,rest:true}];
  const tot=sumA(items.map(d=>d.v));const lp=o.legend||'none';
  let lg={s:'',h:0},aw=W,ax=0,ay=0,ah=H;
  const li=items.map((d,k)=>({n:d.n,c:d.rest?'track':d.other?'muted-mark':k+1}));
  if(lp==='right'){const lw=Math.min(W*.4,Math.max(...items.map(d=>TW(d.n,fs)))+28);aw=W-lw;let y=H/2-items.length*(fs+7)/2+fs;let s='';li.forEach(it=>{s+=`<rect x="${n1(aw+4)}" y="${n1(y-fs*.36-4.5)}" width="9" height="9" rx="2" style="fill:${col(it.c)}"/><text x="${n1(aw+17)}" y="${n1(y)}" class="lg">${esc(trunc(it.n,lw-20,fs))}</text>`;y+=fs+7;});lg={s,h:0};}
  else if(lp==='top'||lp==='bottom'){lg=legendSvg(li,4,lp==='top'?fs+1:H-4-(fs+6)*Math.ceil(li.length/4)+fs,W-8,fs);if(lp==='top'){ay=lg.h;ah=H-lg.h;}else ah=H-lg.h;}
  const outL=o.labels==='out'||o.labels==='detail',semi=!!o.semi;
  const D3=E.look==='3d'&&!semi,ty=D3?.56:1;
  let R=Math.min(aw/2-(outL?Math.min(aw*.28,fs*(o.labels==='detail'?8.4:7.5)):6),((semi?ah*.7:ah/2)-(outL?fs*1.8:5))/(D3?ty*1.05:1));R=Math.max(R,18);
  const dep=D3?Math.max(5,R*.15):0;
  const cx=ax+aw/2,cy=semi?ay+ah*.78:ay+ah/2-dep/2;const ri=R*(o.inner||0);
  const p=(rr,an)=>[cx+rr*Math.cos(an),cy+rr*ty*Math.sin(an)];
  const arc=(rr,an,sw)=>{const [x,y]=p(rr,an);return `A${n1(rr)},${n1(rr*ty)} 0 ${sw}`;};
  let a0=semi?-Math.PI:(o.rot||0)*Math.PI/180-Math.PI/2;const span=semi?Math.PI:Math.PI*2;
  let s='',walls='',lab='';const Lf=[],Rr=[];
  const segs=[];
  items.forEach((d,k)=>{const a=d.v/tot*span;segs.push({d,k,a0,a1:a0+a,a,m:a0+a/2});a0+=a;});
  const full=g=>g.a>=Math.PI*2-1e-6;
  const ellipse=(rr,dy,dir)=>`M${n1(cx-rr)},${n1(cy+dy)}a${n1(rr)},${n1(rr*ty)} 0 1,${dir} ${n1(rr*2)},0a${n1(rr)},${n1(rr*ty)} 0 1,${dir} ${n1(-rr*2)},0`;
  const slicePath=(g,dy)=>{dy=dy||0;const P=(rr,an)=>{const [x,y]=p(rr,an);return n1(x)+','+n1(y+dy);};const big=g.a>Math.PI?1:0;
    if(full(g))return ellipse(R,dy,0)+(ri?ellipse(ri,dy,1):'');
    if(ri)return `M${P(R,g.a0)}A${n1(R)},${n1(R*ty)} 0 ${big},1 ${P(R,g.a1)}L${P(ri,g.a1)}A${n1(ri)},${n1(ri*ty)} 0 ${big},0 ${P(ri,g.a0)}Z`;
    return `M${n1(cx)},${n1(cy+dy)}L${P(R,g.a0)}A${n1(R)},${n1(R*ty)} 0 ${big},1 ${P(R,g.a1)}Z`;};
  if(D3){
    /* side walls: outer rim where it faces the viewer, inner rim of a donut on the far side */
    const span2=(lo,hi,rng)=>{const out=[];for(let k=-1;k<=2;k++){const s0=Math.max(lo,rng[0]+k*Math.PI*2),e0=Math.min(hi,rng[1]+k*Math.PI*2);if(e0>s0+1e-4)out.push([s0,e0]);}return out;};
    const wall=(rr,s0,e0)=>{const [xa,ya]=p(rr,s0),[xb,yb]=p(rr,e0);const big=e0-s0>Math.PI?1:0;return `M${n1(xa)},${n1(ya)}A${n1(rr)},${n1(rr*ty)} 0 ${big},1 ${n1(xb)},${n1(yb)}L${n1(xb)},${n1(yb+dep)}A${n1(rr)},${n1(rr*ty)} 0 ${big},0 ${n1(xa)},${n1(ya+dep)}Z`;};
    const parts=[];
    segs.forEach(g=>{const c=li[g.k].c;
      if(ri)span2(g.a0,g.a1,[Math.PI,Math.PI*2]).forEach(([a,b])=>parts.push({z:-2,d:wall(ri,a,b),c,i:g.d.i}));
      span2(g.a0,g.a1,[0,Math.PI]).forEach(([a,b])=>parts.push({z:Math.sin((a+b)/2),d:wall(R,a,b),c,i:g.d.i}));});
    parts.sort((x,y)=>x.z-y.z).forEach(w=>{walls+=`<path class="pz wl${kc(w.c)}" data-i="${w.i}" d="${w.d}"/>`;});
    walls=`<ellipse cx="${n1(cx)}" cy="${n1(cy+dep+R*ty*.12)}" rx="${n1(R*1.02)}" ry="${n1(R*ty*.92)}" class="pshadow"/>`+walls;
  }
  segs.forEach(g=>{const d=g.d,k=g.k,c=li[k].c,pc=d.v/tot*100;
    s+=`<path class="sl${kc(c)}" data-i="${d.i}"${d.d?` data-d="${d.i}"`:''} d="${slicePath(g)}" style="fill:${col(c)};animation-delay:${k*50}ms" fill-rule="evenodd" data-t="${tipA(d.n,[[fmt(d.v,o.u),o.vn||'Value',c],[pc.toFixed(1)+'%','of total','muted']])}"/>`;
    if(o.labels==='in'&&g.a>.32&&!d.rest){const [lx,ly]=p((R+ri)/2||R*.62,g.m);lab+=`<text x="${n1(lx)}" y="${n1(ly+fs*.36)}" text-anchor="middle" class="li${ki(c)}">${Math.round(pc)}%</text>`;}
    if(outL&&pc>=2.5&&!d.rest){(Math.cos(g.m)>=0?Rr:Lf).push({m:g.m,k,pc,d});}});
  if(E.look!=='flat'){const sh=ri?`<path d="${ellipse(R,0,0)}${ellipse(ri,0,1)}" fill-rule="evenodd" class="sheen"/>`:`<path d="${ellipse(R,0,0)}" class="sheen"/>`;s+=semi?'':sh;}
  const place=(arr,right)=>{arr.sort((a,b)=>Math.sin(a.m)-Math.sin(b.m));let last=-1e9;const gp=o.labels==='detail'?fs*2+4:fs+4;
    arr.forEach(e=>{let y=cy+(R+8)*ty*Math.sin(e.m)+(Math.sin(e.m)>0?dep:0);y=Math.max(y,last+gp);last=y;e.y=y;});
    const ov=(arr.length?arr[arr.length-1].y:0)-(ay+ah-4);if(ov>0)arr.forEach(e=>{e.y-=ov;});
    arr.forEach(e=>{const [ex,ey]=p(R+2,e.m),bx=cx+(R+9)*Math.cos(e.m),lx=right?Math.max(bx,cx+R*.6)+6:Math.min(bx,cx-R*.6)-6;const ey2=ey+(Math.sin(e.m)>0?dep:0);
      lab+=`<path class="lead" d="M${n1(ex)},${n1(ey2)}L${n1(bx)},${n1(e.y)}L${n1(lx)},${n1(e.y)}"/>`;
      const room=right?W-lx-6:lx-6;
      if(o.labels==='detail'){lab+=`<text x="${n1(lx+(right?3:-3))}" y="${n1(e.y-1)}" text-anchor="${right?'start':'end'}" class="lb">${esc(trunc(e.d.n,room,fs))}</text><text x="${n1(lx+(right?3:-3))}" y="${n1(e.y+fs)}" text-anchor="${right?'start':'end'}" class="tk" font-size="${fs-1}">${esc(trunc(fmt(e.d.v,o.u)+' · '+e.pc.toFixed(0)+'%',room,fs-1))}</text>`;}
      else lab+=`<text x="${n1(lx+(right?3:-3))}" y="${n1(e.y+fs*.36)}" text-anchor="${right?'start':'end'}" class="lb">${esc(trunc(e.d.n,room-TW(' 00%',fs),fs))} <tspan class="tk">${Math.round(e.pc)}%</tspan></text>`;});};
  place(Rr,true);place(Lf,false);
  if(o.center){const cv=o.center===true?fmt(tot,o.u):o.center;lab+=`<text x="${n1(cx)}" y="${n1(cy+(semi?-4:fs*.5))}" text-anchor="middle" class="cv pcv" font-size="${n1(Math.min(ri*.52,fs*2.6))}">${esc(cv)}</text><text x="${n1(cx)}" y="${n1(cy+(semi?fs+4:fs*1.9))}" text-anchor="middle" class="tk">${esc(o.cl||'Total')}</text>`;}
  return svgWrap(W,H,fs,`<g class="gm">${walls}${s}</g>`+lab+lg.s);
}};

/* ======================= Treemap ======================= */
function squarify(items,x,y,w,h){
  const out=[];const tot=sumA(items.map(d=>d.v));if(!tot)return out;const k=w*h/tot;
  let rest=items.map(d=>({...d,a:d.v*k}));
  const worst=(row,s)=>{const sm=sumA(row.map(d=>d.a)),mx=Math.max(...row.map(d=>d.a)),mn=Math.min(...row.map(d=>d.a));return Math.max(s*s*mx/(sm*sm),sm*sm/(s*s*mn));};
  while(rest.length){const s=Math.min(w,h);let row=[rest[0]],i=1,wr=worst(row,s);
    while(i<rest.length){const nr=row.concat(rest[i]),nw=worst(nr,s);if(nw<=wr){row=nr;wr=nw;i++;}else break;}
    const ra=sumA(row.map(d=>d.a));
    if(w>=h){const cw=ra/h;let cy=y;row.forEach(d=>{const ch=d.a/cw;out.push({...d,x,y:cy,w:cw,h:ch});cy+=ch;});x+=cw;w-=cw;}
    else{const rh=ra/w;let cx=x;row.forEach(d=>{const cw=d.a/rh;out.push({...d,x:cx,y,w:cw,h:rh});cx+=cw;});y+=rh;h-=rh;}
    rest=rest.slice(row.length);}
  return out;
}
E.treemap={draw(o,st,W,H){
  const fs=FS(W);let s='',lab='';const pad=2;const B3=E.look==='3d';
  const R0=resolve(o,st);
  const tile=(d,ct)=>{const x=d.x+pad/2,y=d.y+pad/2,w=Math.max(0,d.w-pad),h=Math.max(0,d.h-pad);
    s+=`<rect class="m tm${kc(ct)}" data-i="${d.i}"${d.d?` data-d="${d.i}"`:''} x="${n1(x)}" y="${n1(y)}" width="${n1(w)}" height="${n1(h)}" rx="${B3?2:3.5}" style="fill:${col(ct)}" data-t="${tipA((d.p?d.p+' › ':'')+d.n,[[fmt(d.v,o.u),'Sales',ct],[(d.v/d.tot*100).toFixed(1)+'%','of total','muted']].concat(d.m!=null?[[d.m.toFixed(1)+'%','Margin','muted']]:[]))}"/>`;
    if(B3&&w>6&&h>6)s+=`<path class="bvl" d="M${n1(x+1.2)},${n1(y+h-1.2)}V${n1(y+1.2)}H${n1(x+w-1.2)}"/><path class="bvd" d="M${n1(x+w-1.2)},${n1(y+1.2)}V${n1(y+h-1.2)}H${n1(x+1.2)}"/>`;
    if(w>TW(d.n,fs)*0.6+8&&h>fs+6){lab+=`<text x="${n1(x+5)}" y="${n1(y+fs+3)}" class="li${ki(ct)} tml">${esc(trunc(d.n,w-8,fs))}</text>`;if(o.values!==false&&h>fs*2+10)lab+=`<text x="${n1(x+5)}" y="${n1(y+fs*2+5)}" class="li${ki(ct)}" font-weight="500">${fmt(d.v,o.u)}</text>`;}};
  if(o.nest){
    const groups=HP.root.c.map((c,i)=>({n:c.n,v:agg(c)[0],i,c:c.c}));const tot=sumA(groups.map(g=>g.v));
    squarify(groups,0,0,W,H).forEach((g,gi)=>{const hh=fs+8;
      s+=`<rect x="${n1(g.x+1)}" y="${n1(g.y+1)}" width="${n1(g.w-2)}" height="${n1(g.h-2)}" rx="4" class="tmg"/>`;
      lab+=`<text x="${n1(g.x+6)}" y="${n1(g.y+fs+2)}" class="lb">${esc(trunc(g.n,g.w-10,fs))}</text>`;
      squarify(g.c.map((c,k)=>({n:c.n,v:agg(c)[0],i:gi*10+k,p:g.n,tot})),g.x+2,g.y+hh,g.w-4,g.h-hh-2).forEach(d=>tile(d,gi+1));});
  }else{
    let items=R0.cats.map((n,i)=>{const v=R0.dv?R0.dv.vals[i]:null;return {n,v:v?v[o.k||0]:o.v[i],i,m:v&&v[1]!=null&&o.grad?v[1]/v[0]*100:(o.m?o.m[i]:null),d:R0.dv&&R0.dv.rel===1&&R0.dv.drillable[i]&&R0.dv.lvl<R0.dv.max};}).sort((a,b)=>b.v-a.v);
    const tot=sumA(items.map(d=>d.v));items.forEach(d=>{d.tot=tot;});
    let mn=Infinity,mx=-Infinity;if(o.grad)items.forEach(d=>{mn=Math.min(mn,d.m);mx=Math.max(mx,d.m);});
    squarify(items,0,0,W,H).forEach((d,k)=>{const ct=o.grad?'s'+(3+Math.round((d.m-mn)/((mx-mn)||1)*4)):o.hl!=null?(k===o.hl?1:'muted-mark'):k%8+1;tile(d,ct);});
  }
  return svgWrap(W,H,fs,`<g class="gm">${s}</g>`+lab);
}};

/* ======================= Scatter / bubble / dot plot ======================= */
function scatterModel(o,st,W,H){
  const fs=FS(W);
  const frames=o.play?o.play.frames:null;const f=frames?(st.f==null?frames.length-1:st.f):0;
  const pts=frames?frames[f]:o.dot?o.dot.pts:o.pts;
  const all=frames?frames.flat():pts;
  const lx=v=>o.logx?Math.log10(v):v;
  let x0,x1,y0,y1;
  if(o.dot){x0=0;x1=o.dot.cats.length;}else{x0=Math.min(...all.map(p=>lx(p.x)));x1=Math.max(...all.map(p=>lx(p.x)));}
  y0=Math.min(...all.map(p=>p.y));y1=Math.max(...all.map(p=>p.y));
  if(o.sym){x0=y0=Math.min(x0,y0);x1=y1=Math.max(x1,y1);}
  if(o.zeroY)y0=Math.min(0,y0);if(o.zeroX&&!o.logx)x0=Math.min(0,x0);
  if(st.zx){x0=st.zx[0];x1=st.zx[1];}if(st.zy){y0=st.zy[0];y1=st.zy[1];}
  const TX=o.dot?null:o.logx?{lo:Math.floor(x0),hi:Math.ceil(x1),t:[...Array(Math.ceil(x1)-Math.floor(x0)+1)].map((_,i)=>Math.floor(x0)+i)}:ticks(x0,x1+(x1-x0)*.04,W>=560?6:4);
  let ylo=y0-(y1-y0)*.04;if(o.zeroY&&y0>=0)ylo=Math.max(0,ylo);
  const TY=ticks(ylo,y1+(y1-y0)*.06,W>=560?5:4);
  const groups=o.groups||null;
  const lg=groups?legendSvg(groups.map((g,i)=>({n:g,c:i+1,t:'dot'})),2,fs+1,W-4,fs):{s:'',h:0};
  const ylab=t=>fmt(t,o.uy);const xlab=t=>o.logx?fmt(Math.pow(10,t),o.ux):fmt(t,o.ux);
  const top=lg.h+(o.yt?fs+6:6);const L=Math.max(...TY.t.map(t=>TW(ylab(t),fs)))+10;const R=W-Math.max(10,TX?TW(xlab(TX.t[TX.t.length-1]),fs)/2+4:10);const B=H-fs-8-(o.xt?fs+2:0);
  const X=o.dot?(v=>L+(v+.5)/x1*(R-L)):(v=>L+(v-TX.lo)/((TX.hi-TX.lo)||1)*(R-L));
  const Y=v=>B-(v-TY.lo)/((TY.hi-TY.lo)||1)*(B-top);
  const smax=Math.max(...all.map(p=>p.s||1));const rmax=W>=560?26:15;
  const P=pts.map((p,i)=>{let xv=o.dot?p.c:lx(p.x);let jx=0;if(o.dot){jx=(((i*37)%13)/13-.5)*.5;}
    const r=o.size?3+Math.sqrt((p.s||0)/smax)*rmax:(W>=560?5.5:4.5);
    return {k:p.n,i,x:X(xv+jx),y:Y(p.y),r,p};});
  return {fs,P,X,Y,TX,TY,L,R,B,top,lg,xlab,ylab,f,frames,x0,x1,y0,y1};
}
E.scatter={draw(o,st,W,H){
  const m=scatterModel(o,st,W,H);const {fs,P,X,Y,TX,TY,L,R,B,top}=m;
  let g='',s='',lab='',over='';
  const placed=[];const free=b=>!placed.some(z=>b[0]<z[2]&&b[2]>z[0]&&b[1]<z[3]&&b[3]>z[1]);
  const lbl=q=>{if(!(o.labels||(o.play&&o.labels!==false)))return '';const tw=TW(q.p.n,fs);const y0=q.y-fs*.7,y1=q.y+fs*.35;
    const right=[q.x+q.r+3,y0,q.x+q.r+3+tw,y1],left=[q.x-q.r-3-tw,y0,q.x-q.r-3,y1];
    const order=q.x+q.r+3+tw>R?[left,right]:[right,left];
    for(const b of order){if(b[0]<L||b[2]>R+2)continue;if(free(b)){placed.push(b);const isL=b===left;return `<text class="lb" x="${n1(isL?-(q.r+3):q.r+3)}" y="${n1(fs*.36)}"${isL?' text-anchor="end"':''}>${esc(q.p.n)}</text>`;}}return '';};
  TY.t.forEach(t=>{const y=n1(Y(t));if(y<top-1||y>B+1)return;g+=`<line class="gl" x1="${n1(L)}" x2="${n1(R)}" y1="${y}" y2="${y}"/><text x="${n1(L-6)}" y="${n1(y+fs*.35)}" text-anchor="end" class="tk">${m.ylab(t)}</text>`;});
  if(o.dot)o.dot.cats.forEach((c,i)=>{const x=n1(X(i));g+=`<text x="${x}" y="${n1(B+fs+4)}" text-anchor="middle" class="tk">${esc(c)}</text>`;});
  else TX.t.forEach(t=>{const x=n1(X(t));if(x<L-1||x>R+1)return;g+=`<line class="gl" y1="${n1(top)}" y2="${n1(B)}" x1="${x}" x2="${x}"/><text x="${x}" y="${n1(B+fs+4)}" text-anchor="middle" class="tk">${m.xlab(t)}</text>`;});
  if(o.yt)g+=`<text x="${n1(L)}" y="${n1(top-5)}" class="axt">${esc(o.yt)}</text>`;
  if(o.xt)g+=`<text x="${n1(R)}" y="${n1(H-3)}" text-anchor="end" class="axt">${esc(o.xt)}</text>`;
  if(o.sym){const a=Math.max(m.TX.lo,TY.lo),b=Math.min(m.TX.hi,TY.hi);g+=`<path class="symA" d="M${n1(X(a))},${n1(Y(a))}L${n1(X(b))},${n1(Y(b))}L${n1(L)},${n1(top)}Z"/><path class="symB" d="M${n1(X(a))},${n1(Y(a))}L${n1(X(b))},${n1(Y(b))}L${n1(R)},${n1(B)}Z"/><line class="ref" x1="${n1(X(a))}" y1="${n1(Y(a))}" x2="${n1(X(b))}" y2="${n1(Y(b))}"/><text class="reft" x="${n1(L+6)}" y="${n1(top+fs+2)}">Over plan</text><text class="reft" x="${n1(R-4)}" y="${n1(B-6)}" text-anchor="end">Under plan</text>`;}
  if(o.quad){const qx=o.quad.x==='avg'?sumA(P.map(p=>p.p.x))/P.length:o.quad.x,qy=o.quad.y==='avg'?sumA(P.map(p=>p.p.y))/P.length:o.quad.y;const px=n1(X(qx)),py=n1(Y(qy));
    g+=`<rect class="shade" x="${px}" y="${n1(top)}" width="${n1(R-px)}" height="${n1(py-top)}"/>`;over+=`<line class="ref" x1="${px}" x2="${px}" y1="${n1(top)}" y2="${n1(B)}"/><line class="ref" x1="${n1(L)}" x2="${n1(R)}" y1="${py}" y2="${py}"/>`;
    const nm=o.quad.names;if(nm){over+=`<text class="qt" x="${n1(L+5)}" y="${n1(top+fs+2)}">${nm[0]}</text><text class="qt" x="${n1(R-5)}" y="${n1(top+fs+2)}" text-anchor="end">${nm[1]}</text><text class="qt" x="${n1(L+5)}" y="${n1(B-5)}">${nm[2]}</text><text class="qt" x="${n1(R-5)}" y="${n1(B-5)}" text-anchor="end">${nm[3]}</text>`;}}
  if(o.trend||o.ratio){const xs=P.map(p=>o.logx?Math.log10(p.p.x):p.p.x),ys=P.map(p=>p.p.y);
    if(o.trend){const mx=sumA(xs)/xs.length,my=sumA(ys)/ys.length;let a=0,b=0;xs.forEach((x,k)=>{a+=(x-mx)*(ys[k]-my);b+=(x-mx)*(x-mx);});const sl=a/(b||1),ic=my-sl*mx;const xa=m.TX.lo,xb=m.TX.hi;over+=`<line class="tr" x1="${n1(X(xa))}" y1="${n1(Y(ic+sl*xa))}" x2="${n1(X(xb))}" y2="${n1(Y(ic+sl*xb))}"/>`;}
    if(o.ratio){const rt=sumA(ys)/sumA(xs);const xb=Math.min(m.TX.hi,TY.hi/rt);over+=`<line class="ref" x1="${n1(X(0))}" y1="${n1(Y(0))}" x2="${n1(X(xb))}" y2="${n1(Y(rt*xb))}"/><text class="reft" x="${n1(X(xb)-4)}" y="${n1(Y(rt*xb)+fs+2)}" text-anchor="end">Ratio ${rt.toFixed(1)}×</text>`;}}
  const cid='cp'+(++UID);const clip=`<clipPath id="${cid}"><rect x="${n1(L)}" y="${n1(top)}" width="${n1(R-L)}" height="${n1(B-top)}"/></clipPath>`;
  P.forEach(q=>{const p=q.p;const gi=p.k!=null?p.k:p.g!=null?p.g:p.c!=null&&o.dot?p.c:0;const c=col(gi+1);
    const rows=[[o.ux==='$'||o.ux?fmt(p.x,o.ux):String(p.x),o.xt||'X',gi+1],[fmt(p.y,o.uy),o.yt||'Y','muted']];if(o.size)rows.push([fmt(p.s,o.us),o.st||'Size','muted']);if(o.dot)rows.splice(0,1);
    s+=`<g class="pt" data-k="${esc(q.k)}" data-i="${q.i}" style="transform:translate(${n1(q.x)}px,${n1(q.y)}px)" data-t="${tipA(p.n,rows)}"><circle class="hit" r="${Math.max(12,q.r)}"/><circle class="dot${o.size?' bub':''}${kc(gi+1)}" r="${n1(q.r)}" style="fill:${c}"/>${lbl(q)}</g>`;});
  let pl='';if(o.play)pl=`<text class="playlab" x="${n1(R-6)}" y="${n1(top+fs*2.6)}" text-anchor="end" font-size="${fs*2.6}">${m.frames?o.play.yrs[m.f]:''}</text>`;
  return svgWrap(W,H,fs,`<defs>${clip}</defs>`+g+pl+`<g clip-path="url(#${cid})">${over}<g class="gm pts">${s}</g></g>`+lab+m.lg.s,`data-pl="${n1(L)}" data-pr="${n1(R)}" data-pt="${n1(top)}" data-pb="${n1(B)}" data-x0="${m.TX?m.TX.lo:0}" data-x1="${m.TX?m.TX.hi:1}" data-y0="${TY.lo}" data-y1="${TY.hi}"`);
}};

/* ======================= Gantt (preview) ======================= */
E.gantt={draw(o,st,W,H){
  const fs=FS(W),T=GANTT;const groups=[...new Set(T.map(t=>t.g))];
  const rowsArr=[];groups.forEach((g,gi)=>{const ts=T.filter(t=>t.g===g);rowsArr.push({cat:g,gi,s:Math.min(...ts.map(t=>t.s)),e:Math.max(...ts.map(t=>t.e??t.s)),p:sumA(ts.map(t=>t.p*((t.e??t.s)-t.s+1)))/sumA(ts.map(t=>(t.e??t.s)-t.s+1))});ts.forEach(t=>rowsArr.push({...t,gi}));});
  let d0=0,d1=104;if(st.z){const sp=d1-d0;const a=d0+st.z[0]*sp,b=d0+st.z[1]*sp;d0=a;d1=b;}
  if(o.days&&!st.z){d0=14;d1=42;}
  const cols=o.cols||[];const nameW=Math.min(W*(cols.length?.27:.3),130*(W>=560?1.4:1));const colW=W>=560?54:34;const lw=nameW+cols.length*colW;
  const hdr=fs*2+8,L=lw+4,R=W-6,top=hdr,rh=Math.min((H-top-4)/rowsArr.length,W>=560?30:16);
  const X=d=>L+(d-d0)/(d1-d0)*(R-L);
  let s='',g='',lab='',hov='';
  /* axis: months (secondary) + weeks or days (primary) */
  const dayDate=d=>new Date(GANTT_D0.getTime()+d*864e5);
  for(let d=Math.floor(d0);d<=d1;d++){const dt=dayDate(d);const x=X(d);if(x<L-1)continue;
    if(o.days&&(dt.getDay()===0||dt.getDay()===6))g+=`<rect x="${n1(x)}" y="${n1(top)}" width="${n1((R-L)/(d1-d0))}" height="${n1(rowsArr.length*rh)}" class="wkend"/>`;
    if(dt.getDate()===1){g+=`<line class="gl" x1="${n1(x)}" x2="${n1(x)}" y1="${fs+4}" y2="${n1(top+rowsArr.length*rh)}"/><text x="${n1(x+4)}" y="${fs+2}" class="tk tkb">${MON[dt.getMonth()]} 2025</text>`;}
    if(o.days){const dw=(R-L)/(d1-d0),stp=Math.max(1,Math.ceil((TW('00',fs-2)+4)/dw));if(x<R-8&&(d-Math.floor(d0))%stp===0)lab+=`<text x="${n1(x+(R-L)/(d1-d0)/2)}" y="${n1(hdr-5)}" text-anchor="middle" class="tk" font-size="${fs-2}">${dt.getDate()}</text>`;}
    else if(dt.getDay()===1&&x<R-10)lab+=`<text x="${n1(x+2)}" y="${n1(hdr-5)}" class="tk" font-size="${fs-1}">${dt.getDate()}</text>`;}
  g+=`<line class="bl" x1="0" x2="${W}" y1="${n1(top-1)}" y2="${n1(top-1)}"/>`;
  if(cols.length)cols.forEach((c,k)=>{lab+=`<text x="${n1(nameW+k*colW+colW/2)}" y="${n1(hdr-5)}" text-anchor="middle" class="tk tkb" font-size="${fs-1}">${c}</text>`;});
  lab+=`<text x="4" y="${n1(hdr-5)}" class="tk tkb">Task</text>`;
  rowsArr.forEach((r,i)=>{const y=top+i*rh;const ctk=o.mode==='granular'?r.gi+1:1,cc=col(ctk);
    if(r.cat){g+=`<rect x="0" y="${n1(y)}" width="${W}" height="${n1(rh)}" style="fill:color-mix(in oklab, ${cc} ${o.mode==='granular'?18:14}%, transparent)"/>`;lab+=`<text x="4" y="${n1(y+rh/2+fs*.36)}" class="lb">${esc(trunc(r.cat,nameW-6,fs))}</text>`;}
    else lab+=`<text x="${n1(fs)}" y="${n1(y+rh/2+fs*.36)}" class="tk tkn">${esc(trunc(r.n,nameW-fs-4,fs))}</text>`;
    if(cols.includes('Owner')&&!r.cat)lab+=`<text x="${n1(nameW+cols.indexOf('Owner')*colW+colW/2)}" y="${n1(y+rh/2+fs*.36)}" text-anchor="middle" class="tk">${r.o}</text>`;
    if(cols.includes('Done')){lab+=`<text x="${n1(nameW+cols.indexOf('Done')*colW+colW/2)}" y="${n1(y+rh/2+fs*.36)}" text-anchor="middle" class="${r.cat?'lb':'tk'}">${Math.round(r.p*100)}%</text>`;}
    const bh=r.cat?rh*.3:rh*.56,by=y+(rh-bh)/2;
    if(r.e==null&&!r.cat){const x=X(r.s),k=bh*.62;if(x>=L-k&&x<=R+k)s+=`<path class="m ms" data-i="${i}" d="M${n1(x)},${n1(by+bh/2-k)}L${n1(x+k)},${n1(by+bh/2)}L${n1(x)},${n1(by+bh/2+k)}L${n1(x-k)},${n1(by+bh/2)}Z" style="fill:${o.mode==='status'?'var(--ink)':cc}"/>`;}
    else{const xa=Math.max(L,X(r.s)),xb=Math.min(R,X((r.e??r.s)+1));if(xb>xa){
      let ft=ctk;if(o.mode==='status'&&!r.cat){ft=r.p>=1?'good':(o.today!=null&&r.e<o.today&&r.p<1)?'crit':(o.today!=null&&r.s<o.today&&r.p<(o.today-r.s)/(r.e-r.s))?'warn':'c1';}const fill=col(ft);
      if(o.prog==='fill'&&!r.cat){s+=`<path d="${bp(xa,by,xb-xa,bh,3,'all')}" class="gbo" style="stroke:${fill}"/>`;const xp=Math.min(xb,X(r.s+(r.e-r.s+1)*r.p));if(xp>xa)s+=`<path class="m${kc(ft)}" data-i="${i}" d="${bp(xa,by,xp-xa,bh,3,'all')}" style="fill:${fill}"/>`;}
      else{s+=`<path class="m${kc(ft)}" data-i="${i}" d="${bp(xa,by,xb-xa,bh,r.cat?2:3,'all')}" style="fill:${fill}${r.cat?';fill-opacity:.85':''}"/>`;
        if(!r.cat&&r.p<1&&o.prog!=='none'){const xp=Math.max(xa,X(r.s+((r.e??r.s)-r.s+1)*r.p));s+=`<path d="${bp(xp,by,xb-xp,bh,xp>xa?0:3,'all')}" class="gov"/>`;}}}}
    hov+=`<rect class="hit" data-i="${i}" x="0" y="${n1(y)}" width="${W}" height="${n1(rh)}" data-t="${tipA(r.cat||r.n,[[r.e==null&&!r.cat?'Milestone':fmtD(r.s)+' – '+fmtD(r.e),'Dates',r.gi+1],[Math.round(r.p*100)+'%','Complete','muted']].concat(r.o?[[r.o,'Owner','muted']]:[]))}"/>`;});
  if(o.today!=null){const x=n1(X(o.today));if(x>=L&&x<=R)lab+=`<line class="today" x1="${x}" x2="${x}" y1="${n1(top-2)}" y2="${n1(top+rowsArr.length*rh)}"/><text class="todayt" x="${n1(x+3)}" y="${n1(top+fs-1)}">Today</text>`;}
  g+=`<line class="gl" x1="${n1(lw)}" x2="${n1(lw)}" y1="${n1(top)}" y2="${n1(top+rowsArr.length*rh)}"/>`;
  return svgWrap(W,H,fs,g+`<g class="gm">${s}</g>`+lab+hov,`data-pl="${n1(L)}" data-pr="${n1(R)}" data-gantt="1"`);
}};
function fmtD(d){if(d==null)return '';const dt=new Date(GANTT_D0.getTime()+d*864e5);return MON[dt.getMonth()]+' '+dt.getDate();}
