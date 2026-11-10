/* ============================================================
   Extended visuals II — part-to-whole and hierarchy, time and
   calendars, finance, gauges, and build-your-own visuals.
   ============================================================ */
const xP=(cx,cy,r,a)=>n1(cx+r*Math.cos(a))+','+n1(cy+r*Math.sin(a));
function xSect(cx,cy,r1,r2,a0,a1){
  if(a1-a0>=Math.PI*2-1e-6){const ring=r=>`M${n1(cx-r)},${n1(cy)}a${n1(r)},${n1(r)} 0 1,0 ${n1(r*2)},0a${n1(r)},${n1(r)} 0 1,0 ${n1(-r*2)},0`;return ring(r2)+(r1>0?ring(r1):'');}
  const lg=a1-a0>Math.PI?1:0;
  if(r1<=0)return `M${n1(cx)},${n1(cy)}L${xP(cx,cy,r2,a0)}A${n1(r2)},${n1(r2)} 0 ${lg},1 ${xP(cx,cy,r2,a1)}Z`;
  return `M${xP(cx,cy,r2,a0)}A${n1(r2)},${n1(r2)} 0 ${lg},1 ${xP(cx,cy,r2,a1)}L${xP(cx,cy,r1,a1)}A${n1(r1)},${n1(r1)} 0 ${lg},0 ${xP(cx,cy,r1,a0)}Z`;
}
const xMix=(c,p)=>`color-mix(in oklab,${col(c)} ${p}%,var(--surface))`;

/* ======================= Sunburst (click to zoom) ======================= */
E.sunburst={draw(o,st,W,H){
  const fs=FS(W),Hh=o.tree,path=(st.sb||[]).map(Number);let node=Hh.root;const names=[];for(const p of path){node=node.c[p];names.push(node.n);}
  const depth=Math.min(o.depth||2,Hh.levels.length-path.length),cx=W/2,cy=H/2,R=Math.min(W,H)/2-4,r0=R*(depth>2?.3:.34),rw=(R-r0)/depth;
  const tot=agg(node)[0];let s='',lab='';const pad=.005;
  const walk=(n,a0,a1,d,ci,chain,cn)=>{if(d>depth||!n.c)return;const nt=agg(n)[0];let a=a0;
    n.c.forEach((ch,k)=>{const v=agg(ch)[0],span=(a1-a0)*v/nt,c=ci||k+1,b0=a+(span>.02?pad:0),b1=a+span-(span>.02?pad:0);
      const fill=d===1?col(c):xMix(c,d===2?(ci?68:72):52),abs=[...path,...chain,k],can=!!ch.c&&abs.length<Hh.levels.length;
      s+=`<path class="sb${d===1?' sb1':''}${d===1?kc(c):''}" data-i="${chain.length?chain[0]:k}" d="${xSect(cx,cy,r0+rw*(d-1)+.5,r0+rw*d-.5,b0-Math.PI/2,b1-Math.PI/2)}" style="fill:${fill}"${can?` data-act="sb:${abs.join('.')}"`:''} data-t="${tipA([...names,...cn,ch.n].join(' › '),[[fmt(v,'$'),'Sales',c],[(v/nt*100).toFixed(1)+'%','of '+n.n,'muted']].concat(can?[['Click to zoom in','','muted']]:[]))}"/>`;
      const mid=(a+span/2)-Math.PI/2,rm=r0+rw*(d-.5),arcL=span*rm,t=ch.n;
      if(d===1&&arcL>TW(t,fs)+6&&rw>fs+4){const [lx,ly]=[cx+rm*Math.cos(mid),cy+rm*Math.sin(mid)];lab+=`<text x="${n1(lx)}" y="${n1(ly+fs*.36)}" text-anchor="middle" class="li${ki(c)} sbl">${esc(t)}</text>`;}
      else if(arcL>fs+1&&rw>TW(t,fs-1)+8){let deg=mid*180/Math.PI;const flip=Math.cos(mid)<0;if(flip)deg+=180;const [lx,ly]=[cx+rm*Math.cos(mid),cy+rm*Math.sin(mid)];lab+=`<text transform="translate(${n1(lx)},${n1(ly)}) rotate(${n1(deg)})" y="${n1((fs-1)*.36)}" text-anchor="middle" class="${d===1?'li'+ki(c):'lbt'} sbl" font-size="${fs-1}">${esc(t)}</text>`;}
      walk(ch,a,a+span,d+1,c,[...chain,k],[...cn,ch.n]);a+=span;});};
  walk(node,0,Math.PI*2,1,path.length?path[0]+1:0,[],[]);
  const up=path.length>0;
  s+=`<circle class="sbc${up?' up':''}" cx="${n1(cx)}" cy="${n1(cy)}" r="${n1(r0-2)}"${up?' data-act="sbup" role="button" aria-label="Zoom out"':''}/>`;
  lab+=`<text x="${n1(cx)}" y="${n1(cy-(up?fs*.9:fs*.2))}" text-anchor="middle" class="cv" font-size="${n1(Math.min(r0*.42,fs*2))}">${fmt(tot,'$')}</text><text x="${n1(cx)}" y="${n1(cy+fs*1.1)}" text-anchor="middle" class="tk" font-size="${fs-1}">${esc(trunc(up?node.n:'All sales',r0*1.9,fs-1))}</text>`;
  if(up)lab+=`<text x="${n1(cx)}" y="${n1(cy+fs*2.3)}" text-anchor="middle" class="tk sbu" data-act="sbup">↑ Back</text>`;
  return svgWrap(W,H,fs,`<g class="gm">${s}</g>`+lab);
},act(o,st,verb,arg){if(verb==='sb'){st.sb=arg.split('.').map(Number);return 'drill';}if(verb==='sbup'){st.sb=(st.sb||[]).slice(0,-1);return 'drill';}}};

/* ======================= Circle packing (click to zoom) ======================= */
E.pack={draw(o,st,W,H){
  const fs=FS(W),P=o.pack||PACK,z=st.pk==null?null:+st.pk,zc=z==null?null:P.find(p=>p.d===1&&p.c===z);
  const view=zc?{x:zc.x,y:zc.y,r:zc.r*1.04}:{x:.5,y:.5,r:.5};const k=Math.min(W,H)/(view.r*2)*(zc?1:.98);
  const X=v=>W/2+(v-view.x)*k,Y=v=>H/2+(v-view.y)*k;let s='',lab='';
  P.forEach((p,i)=>{const r=p.r*k,c=p.c+1;if(r<.4)return;const cx=X(p.x),cy=Y(p.y);if(cx+r<0||cx-r>W||cy+r<0||cy-r>H)return;
    const tt=` data-t="${tipA((p.p?p.p+' › ':'')+p.n,[[fmt(p.v,'$'),'Sales',c]].concat(p.d===1&&z==null?[['Click to zoom in','','muted']]:[]))}"`;
    if(p.d===1)s+=`<circle class="pk1${z===p.c?' on':''}" data-i="${p.c}" cx="${n1(cx)}" cy="${n1(cy)}" r="${n1(r)}" style="fill:${xMix(c,14)};stroke:${col(c)}"${z==null?` data-act="pk:${p.c}"`:''}${tt}/>`;
    else if(p.d===2)s+=`<circle class="pk2" data-i="${p.c}" cx="${n1(cx)}" cy="${n1(cy)}" r="${n1(r)}" style="fill:${xMix(c,30)}"${z==null?` data-act="pk:${p.c}"`:''}${tt}/>`;
    else s+=`<circle class="bub pk3${kc(c)}" data-i="${p.c}" cx="${n1(cx)}" cy="${n1(cy)}" r="${n1(Math.max(.8,r-.6))}" style="fill:${col(c)}"${z==null?` data-act="pk:${p.c}"`:''}${tt}/>`;});
  const placed=[];const put=(x,y,t,cls,f)=>{const w=TW(t,f);const b=[x-w/2,y-f,x+w/2,y+3];if(placed.some(q=>!(b[2]<q[0]||b[0]>q[2]||b[3]<q[1]||b[1]>q[3])))return;placed.push(b);lab+=`<text x="${n1(x)}" y="${n1(y)}" text-anchor="middle" class="${cls}" font-size="${f}">${esc(t)}</text>`;};
  if(z==null)P.filter(p=>p.d===1).forEach(p=>put(X(p.x),Y(p.y-p.r)+fs+4,p.n,'lb pkl',fs+1));
  else{P.filter(p=>p.d===2&&p.c===z).forEach(p=>{const r=p.r*k;put(X(p.x),Y(p.y-p.r)+fs+3,p.n,'lb pkl',fs);});
    P.filter(p=>p.d===3&&p.c===z).forEach(p=>{const r=p.r*k;if(r*2>TW(p.n,fs-1)+4)put(X(p.x),Y(p.y)+(fs-1)*.36,p.n,'li'+ki(z+1),fs-1);});
    s=`<rect class="hit" width="${W}" height="${H}" data-act="pkup"/>`+s;lab+=`<g class="sbtn" data-act="pkup" role="button"><rect x="4" y="4" width="${n1(TW('‹ All categories',fs-1)+14)}" height="${fs+8}" rx="${(fs+8)/2}"/><text x="${n1(4+(TW('‹ All categories',fs-1)+14)/2)}" y="${n1(4+(fs+8)/2+(fs-1)*.36)}" text-anchor="middle" font-size="${fs-1}">‹ All categories</text></g>`;}
  return svgWrap(W,H,fs,`<g class="gm">${s}</g>`+lab);
},act(o,st,verb,arg){if(verb==='pk'){st.pk=+arg;return 'drill';}if(verb==='pkup'){st.pk=null;return 'drill';}}};

/* ======================= Mekko ======================= */
E.mekko={draw(o,st,W,H){
  const fs=FS(W),C=o.cols,Sg=o.segs,M=o.m,ct=C.map((_,j)=>sumA(Sg.map((_,i)=>M[i][j]))),tot=sumA(ct);
  const lg=legendSvg(Sg.map((n,i)=>({n,c:i+1})),4,fs+1,W-8,fs);const L=xYw(0,1,'pct',fs),R=W-4,top=lg.h+4,B=H-fs*2-10,gap=2.5;
  const ax=xYax(0,1,L,R,top,B,fs,'pct',4);const ww=R-L-gap*(C.length-1);let x=L,s='',lab='';
  C.forEach((c,j)=>{const w=ww*ct[j]/tot;let yb=B;
    Sg.forEach((sg,i)=>{const v=M[i][j],h=(B-top)*v/ct[j],yt=yb-h;const tt=` data-t="${tipA(c+' · '+sg,[[fmt(v,o.u),'Sales',i+1],[(v/ct[j]*100).toFixed(1)+'%','of '+c,'muted'],[(v/tot*100).toFixed(1)+'%','of total','muted']])}"`;
      s+=`<rect class="m mk2${kc(i+1)}" data-i="${i}" x="${n1(x)}" y="${n1(yt+(i?0:0))}" width="${n1(w)}" height="${n1(Math.max(0,h-gap/2))}" rx="2" style="fill:${col(i+1)};animation-delay:${j*60}ms"${tt}/>`;
      const t=o.labels==='value'?fmt(v,o.u):Math.round(v/ct[j]*100)+'%';if(w>TW(t,fs-1)+8&&h>fs+4)lab+=`<text x="${n1(x+w/2)}" y="${n1(yt+h/2+(fs-1)*.36)}" text-anchor="middle" class="li${ki(i+1)}" font-size="${fs-1}">${t}</text>`;yb=yt;});
    lab+=`<text x="${n1(x+w/2)}" y="${n1(B+fs+3)}" text-anchor="middle" class="tkn">${esc(trunc(c,w,fs))}</text><text x="${n1(x+w/2)}" y="${n1(B+fs*2+5)}" text-anchor="middle" class="tk" font-size="${fs-1}">${esc(trunc(fmt(ct[j],o.u)+' · '+Math.round(ct[j]/tot*100)+'%',w,fs-1))}</text>`;x+=w+gap;});
  return svgWrap(W,H,fs,ax.g+`<g class="gm">${s}</g>`+lab+lg.s);
}};

/* ======================= Waffle ======================= */
E.waffle={draw(o,st,W,H){
  const fs=FS(W),big=W>=560;let s='',lab='';
  const grid=(x0,y0,size,fills,tip)=>{const c=size/(10+9*.16),g=c*.16;let out='';for(let k=0;k<100;k++){const r=9-Math.floor(k/10),cc=k%10,f=fills[k];
    out+=`<rect class="${f?'wf gf'+kc(f.c):'wf0'}"${f?` data-i="${f.i}"`:''} x="${n1(x0+cc*(c+g))}" y="${n1(y0+r*(c+g))}" width="${n1(c)}" height="${n1(c)}" rx="${n1(c*.22)}" style="${f?'fill:'+col(f.c)+';':''}animation-delay:${k*7}ms"${f&&tip?` data-t="${tip(f)}"`:''}/>`;}return out;};
  if(o.items){const n=o.items.length,cw=W/n,size=Math.min(cw-(big?28:10),H-fs*3.6-6);
    o.items.forEach((it,j)=>{const x0=cw*j+(cw-size)/2,y0=fs*1.6+4;const fills=Array(100).fill(null).map((_,k)=>k<Math.round(it.pct)?{c:it.c||1,i:j}:null);
      s+=grid(x0,y0,size,fills,()=>tipA(it.n,[[it.pct+'%','Share',it.c||1]]));lab+=`<text x="${n1(cw*(j+.5))}" y="${fs+2}" text-anchor="middle" class="smt">${esc(trunc(it.n,cw-4,fs))}</text><text x="${n1(cw*(j+.5))}" y="${n1(y0+size+fs*1.6+2)}" text-anchor="middle" class="cv" font-size="${fs*1.5}">${it.pct}%</text>`;});
  }else if(o.parts){const tot=sumA(o.parts.map(p=>p.v));let acc=0,k0=0;const fills=Array(100).fill(null);const share=o.parts.map(p=>p.v/tot*100);
    const cnt=share.map(Math.floor);let rem=100-sumA(cnt);share.map((v,i)=>[v-Math.floor(v),i]).sort((a,b)=>b[0]-a[0]).forEach(([,i])=>{if(rem>0){cnt[i]++;rem--;}});
    cnt.forEach((n,i)=>{for(let k=0;k<n;k++)fills[k0+k]={c:o.parts[i].c||i+1,i};k0+=n;});
    const size=Math.min(H-8,W*.52),x0=4,y0=(H-size)/2;s+=grid(x0,y0,size,fills,f=>tipA(o.parts[f.i].n,[[fmt(o.parts[f.i].v,o.u),'Sales',f.c],[cnt[f.i]+'%','of total','muted']]));
    const lx=x0+size+(big?28:12);let y=H/2-o.parts.length*(fs*2.6)/2+fs;
    o.parts.forEach((p,i)=>{lab+=`<rect x="${n1(lx)}" y="${n1(y-fs*.8)}" width="${fs}" height="${fs}" rx="2.5" style="fill:${col(p.c||i+1)}"/><text x="${n1(lx+fs+6)}" y="${n1(y)}" class="lbt" font-weight="600">${esc(p.n)}</text><text x="${n1(lx+fs+6)}" y="${n1(y+fs+2)}" class="tk">${cnt[i]}% · ${fmt(p.v,o.u)}</text>`;y+=fs*2.6;});
  }else{const size=Math.min(H-8,W*.5),x0=big?20:6,y0=(H-size)/2;const n=Math.round(o.pct);const fills=Array(100).fill(null).map((_,k)=>k<n?{c:o.c||1,i:0}:null);
    s+=grid(x0,y0,size,fills,()=>tipA(o.n,[[o.pct+'%',o.n,o.c||1]]));const lx=x0+size+(big?34:14),fsz=Math.min(H*.3,(W-lx-6)/2.6);
    lab+=`<text x="${n1(lx)}" y="${n1(H/2+fsz*.2)}" class="cv wfv" font-size="${n1(fsz)}" style="fill:${col(o.c||1)}">${o.pct}%</text>`;
    const words=String(o.n).split(' ');let line='',yy=H/2+fsz*.2+fs*1.8;const mw=W-lx-6;words.forEach(w=>{if(TW(line+' '+w,fs)>mw&&line){lab+=`<text x="${n1(lx)}" y="${n1(yy)}" class="tkn">${esc(line)}</text>`;yy+=fs+3;line=w;}else line=line?line+' '+w:w;});if(line)lab+=`<text x="${n1(lx)}" y="${n1(yy)}" class="tkn">${esc(line)}</text>`;}
  return svgWrap(W,H,fs,`<g class="gm">${s}</g>`+lab);
}};

/* ======================= Pictogram (infographic) ======================= */
const XPERSON='M5,0.4a3,3 0 1,1 -0.01,0Z M1.4,8.6Q1.4,7 3,7H7Q8.6,7 8.6,8.6V14.2H7.3V21.6H5.6V15.4H4.4V21.6H2.7V14.2H1.4Z';
E.picto={draw(o,st,W,H){
  const fs=FS(W),big=W>=560;let s='',lab='',defs='';
  const person=(x,y,sc,c,frac,i,tt)=>{let g=`<g transform="translate(${n1(x)},${n1(y)}) scale(${n1(sc)})"${tt?` data-i="${i}" data-t="${tt}"`:''}><path class="pp0" d="${XPERSON}"/>`;
    if(frac>0){if(frac<1){const id='pc'+(++UID);defs+=`<clipPath id="${id}"><rect x="0" y="0" width="${n1(10*frac)}" height="22"/></clipPath>`;g+=`<path class="pp gf${kc(c)}" d="${XPERSON}" clip-path="url(#${id})" style="fill:${col(c)}"/>`;}else g+=`<path class="pp gf${kc(c)}" d="${XPERSON}" style="fill:${col(c)}"/>`;}
    return g+'</g>';};
  if(o.mode==='people'){const n=o.of||10,filled=o.v,sz=Math.min((W-20)/(n*1.15),(H*.46)/22*10);const sc=sz/10,gap=sz*.15,tw=n*(sz+gap)-gap,x0=(W-tw)/2,y0=H*.04;
    for(let k=0;k<n;k++)s+=person(x0+k*(sz+gap),y0,sc,o.c||1,Math.max(0,Math.min(1,filled-k)),0,tipA(o.title,[[filled+' of '+n,o.n,o.c||1]]));
    const bf=Math.min(fs*3.4,H*.17),ty=y0+22*sc+bf+6;lab+=`<text x="${n1(W/2)}" y="${n1(ty)}" text-anchor="middle" class="cv wfv" font-size="${n1(bf)}" style="fill:${col(o.c||1)}">${filled} in ${n}</text><text x="${n1(W/2)}" y="${n1(ty+fs*1.7)}" text-anchor="middle" class="lbt" font-weight="650" font-size="${fs+1}">${esc(trunc(o.title,W-12,fs+1))}</text><text x="${n1(W/2)}" y="${n1(ty+fs*3.2)}" text-anchor="middle" class="tk">${esc(trunc(o.sub||'',W-12,fs))}</text>`;}
  else{const rows=o.rows,lw=Math.max(...rows.map(r=>TW(r.n,fs)))+12,vw=TW(fmt(Math.max(...rows.map(r=>r.v)),o.u),fs)+10,unit=o.unit,maxI=Math.max(...rows.map(r=>Math.ceil(r.v/unit)));
    const top=fs+10,rh=(H-top-4)/rows.length,sz=Math.min(rh*.8/22*10,(W-lw-vw-8)/(maxI*1.12)),sc=sz/10,gap=sz*.12;
    lab+=`<text x="${n1(W-4)}" y="${fs}" text-anchor="end" class="tk"><tspan class="tkb">Each icon</tspan> = ${fmt(unit,o.u)} ${esc(o.unitN||'')}</text>`;
    rows.forEach((r,i)=>{const cy=top+rh*(i+.5),y0=cy-11*sc,n=r.v/unit;for(let k=0;k<Math.ceil(n);k++)s+=person(lw+k*(sz+gap),y0,sc,r.c||i+1,Math.min(1,n-k),i,tipA(r.n,[[fmt(r.v,o.u),o.vn||'Customers',r.c||i+1]]));
      lab+=`<text x="${n1(lw-8)}" y="${n1(cy+fs*.36)}" text-anchor="end" class="tkn">${esc(r.n)}</text><text x="${n1(lw+Math.ceil(n)*(sz+gap)+4)}" y="${n1(cy+fs*.36)}" class="tk2">${fmt(r.v,o.u)}</text>`;});}
  return svgWrap(W,H,fs,(defs?`<defs>${defs}</defs>`:'')+`<g class="gm">${s}</g>`+lab);
}};

/* ======================= Aster plot ======================= */
E.aster={draw(o,st,W,H){
  const fs=FS(W),it=o.items,tw=sumA(it.map(d=>d.w)),lw=Math.max(...it.map(d=>TW(d.n,fs)))+10,R=Math.max(30,Math.min(H/2-fs-6,W/2-lw-8)),r0=R*.3,cx=W/2,cy=H/2;
  let a=-Math.PI/2,s='',lab='';const score=sumA(it.map(d=>d.s*d.w))/tw;
  it.forEach((d,i)=>{const span=d.w/tw*Math.PI*2,a0=a+.012,a1=a+span-.012,c=d.c||i+1,rr=r0+(R-r0)*d.s/100;
    s+=`<path class="ast0" d="${xSect(cx,cy,r0,R,a0,a1)}"/><path class="sl ast${kc(c)}" data-i="${i}" d="${xSect(cx,cy,r0,rr,a0,a1)}" style="fill:${col(c)};animation-delay:${i*60}ms" data-t="${tipA(d.n,[[d.s+' / 100','Score',c],[Math.round(d.w/tw*100)+'%','Weight','muted']])}"/>`;
    const m=a+span/2,cs=Math.cos(m),sn=Math.sin(m);lab+=`<text x="${n1(cx+(R+6)*cs)}" y="${n1(cy+(R+6)*sn+fs*.36+(Math.abs(cs)<.25?(sn>0?fs*.4:-fs*.2):0))}" text-anchor="${Math.abs(cs)<.25?'middle':cs>0?'start':'end'}" class="tkn">${esc(d.n)} <tspan class="tkb">${d.s}</tspan></text>`;a+=span;});
  if(E.look!=='flat')s+=`<circle cx="${n1(cx)}" cy="${n1(cy)}" r="${n1(R)}" class="sheen"/>`;
  lab+=`<circle cx="${n1(cx)}" cy="${n1(cy)}" r="${n1(r0-2)}" class="sbc"/><text x="${n1(cx)}" y="${n1(cy+fs*.2)}" text-anchor="middle" class="cv" font-size="${n1(Math.min(r0*.7,fs*2.4))}">${Math.round(score)}</text><text x="${n1(cx)}" y="${n1(cy+fs*1.4)}" text-anchor="middle" class="tk" font-size="${fs-1.5}">${esc(trunc(o.cl||'Overall',r0*1.8,fs-1.5))}</text>`;
  return svgWrap(W,H,fs,`<g class="gm">${s}</g>`+lab);
}};

/* ======================= Rose (polar area) ======================= */
E.rose={draw(o,st,W,H){
  const fs=FS(W),cats=o.cats,n=cats.length,ser=o.series,cum=cats.map((_,k)=>sumA(ser.map(s=>s.v[k]))),vmax=Math.max(...cum);
  const lg=ser.length>1?legendSvg(ser.map((s,i)=>({n:s.n,c:s.c||i+1})),4,fs+1,W*.28,fs):{s:'',h:0};
  const R=Math.min(H/2-fs-6,W/2-30),r0=R*.08,cx=W/2+(ser.length>1&&W<560?W*.08:0),cy=H/2,rr=v=>r0+Math.sqrt(v/vmax)*(R-r0),step=Math.PI*2/n;let s='',g='',lab='';
  const T=ticks(0,vmax,3);T.t.filter(t=>t>0&&rr(t)<R*.96).forEach(t=>{g+=`<circle class="rg" cx="${n1(cx)}" cy="${n1(cy)}" r="${n1(rr(t))}"/>`;});
  cats.forEach((c,k)=>{const a0=-Math.PI/2+k*step+.02,a1=-Math.PI/2+(k+1)*step-.02;let acc=0;
    ser.forEach((sr,si)=>{const v=sr.v[k],r1=rr(acc),r2=rr(acc+v),cc=sr.c||(ser.length>1?si+1:'s'+(3+Math.round(v/vmax*4)));acc+=v;
      s+=`<path class="sl rs2${kc(cc)}" data-i="${ser.length>1?si:k}" d="${xSect(cx,cy,acc-v>0?r1:0,r2,a0,a1)}" style="fill:${col(cc)};animation-delay:${k*40}ms" data-t="${tipA(c+(ser.length>1?' · '+sr.n:''),[[fmt(v,o.u),o.vn||'Sales',cc]])}"/>`;});
    const m=-Math.PI/2+(k+.5)*step,cs=Math.cos(m),sn=Math.sin(m);lab+=`<text x="${n1(cx+(R+7)*cs)}" y="${n1(cy+(R+7)*sn+fs*.36)}" text-anchor="${Math.abs(cs)<.3?'middle':cs>0?'start':'end'}" class="tk">${esc(c)}</text>`;});
  return svgWrap(W,H,fs,g+`<g class="gm">${s}</g>`+lab+lg.s);
}};

/* ======================= Venn ======================= */
function xLens(r1,r2,d){if(d>=r1+r2)return 0;if(d<=Math.abs(r1-r2))return Math.PI*Math.min(r1,r2)**2;const a=r1*r1*Math.acos((d*d+r1*r1-r2*r2)/(2*d*r1)),b=r2*r2*Math.acos((d*d+r2*r2-r1*r1)/(2*d*r2)),c=.5*Math.sqrt((-d+r1+r2)*(d+r1-r2)*(d-r1+r2)*(d+r1+r2));return a+b-c;}
function xDist(r1,r2,A){let lo=Math.abs(r1-r2),hi=r1+r2;for(let k=0;k<60;k++){const m=(lo+hi)/2;if(xLens(r1,r2,m)>A)lo=m;else hi=m;}return (lo+hi)/2;}
E.venn={draw(o,st,W,H){
  const fs=FS(W),S=o.sets,n=S.length,ov=o.ov,r=S.map(s=>Math.sqrt(s.v/Math.PI));let C;
  if(n===2)C=[[0,0],[xDist(r[0],r[1],ov.ab),0]];
  else{const dab=xDist(r[0],r[1],ov.ab),dac=xDist(r[0],r[2],ov.ac),dbc=xDist(r[1],r[2],ov.bc);const x=(dac*dac-dbc*dbc+dab*dab)/(2*dab),y=Math.sqrt(Math.max(0,dac*dac-x*x));C=[[0,0],[dab,0],[x,y]];}
  const x0=Math.min(...C.map((c,i)=>c[0]-r[i])),x1=Math.max(...C.map((c,i)=>c[0]+r[i])),y0=Math.min(...C.map((c,i)=>c[1]-r[i])),y1=Math.max(...C.map((c,i)=>c[1]+r[i]));
  const padT=fs+10,k=Math.min((W-16)/(x1-x0),(H-padT-8)/(y1-y0)),ox=(W-(x1-x0)*k)/2-x0*k,oy=padT+(H-padT-8-(y1-y0)*k)/2-y0*k;
  const cc=C.map(c=>[ox+c[0]*k,oy+c[1]*k]),rr=r.map(v=>v*k);let s='',lab='';
  S.forEach((st_,i)=>{s+=`<circle class="vn${kc(st_.c||i+1)}" data-i="${i}" cx="${n1(cc[i][0])}" cy="${n1(cc[i][1])}" r="${n1(rr[i])}" style="fill:${col(st_.c||i+1)};stroke:${col(st_.c||i+1)}" data-t="${tipA(st_.n,[[fmt(st_.v,o.u),'All '+(o.vn||'customers'),st_.c||i+1]])}"/>`;});
  /* region values */
  const val={};if(n===2){val[1]=S[0].v-ov.ab;val[2]=S[1].v-ov.ab;val[3]=ov.ab;}
  else{const abc=ov.abc;val[1]=S[0].v-ov.ab-ov.ac+abc;val[2]=S[1].v-ov.ab-ov.bc+abc;val[4]=S[2].v-ov.ac-ov.bc+abc;val[3]=ov.ab-abc;val[5]=ov.ac-abc;val[6]=ov.bc-abc;val[7]=abc;}
  const best={};for(let gx=0;gx<=90;gx++)for(let gy=0;gy<=60;gy++){const px=gx/90*W,py=padT+gy/60*(H-padT);let m=0,dmin=1e9;cc.forEach((c,i)=>{const d=Math.hypot(px-c[0],py-c[1]);if(d<rr[i])m|=1<<i;dmin=Math.min(dmin,Math.abs(d-rr[i]));});if(!m)continue;if(!best[m]||dmin>best[m].d)best[m]={x:px,y:py,d:dmin};}
  Object.keys(val).forEach(m=>{const b=best[m];if(!b)return;const names=S.filter((_,i)=>m&(1<<i)).map(q=>q.n);const big=+m===7||(n===2&&+m===3);
    lab+=`<text x="${n1(b.x)}" y="${n1(b.y+fs*.36)}" text-anchor="middle" class="${big?'cv':'tk2'}" font-size="${big?fs+2:fs}">${fmt(val[m],o.u)}</text>`;
    s+=`<circle class="hit" cx="${n1(b.x)}" cy="${n1(b.y)}" r="${n1(Math.max(8,b.d*.8))}" data-t="${tipA(names.join(' and ')+(names.length<n?' only':''),[[fmt(val[m],o.u),o.vn||'Customers','ink']])}"/>`;});
  S.forEach((q,i)=>{const b=best[1<<i];if(!b)return;const t=q.n,w=TW(t,fs);const x=Math.max(w/2+2,Math.min(W-w/2-2,b.x));lab+=`<text x="${n1(x)}" y="${n1(b.y-fs*.8)}" text-anchor="middle" class="lbt vnl" font-weight="650">${esc(t)}</text>`;});
  return svgWrap(W,H,fs,`<g class="gm">${s}</g>`+lab);
}};

/* ======================= Word cloud ======================= */
E.words={draw(o,st,W,H){
  const fs=FS(W),ws=o.words.slice().sort((a,b)=>b.v-a.v),vmax=ws[0].v,vmin=ws[ws.length-1].v,fmin=W>=560?12:8.5,fmax=W>=560?52:26;
  const lg=o.color==='group'?legendSvg(o.groups.map((n,i)=>({n,c:i+1})),4,H-4,W-8,fs):legendSvg([{n:'Positive',c:'dpos'},{n:'Neutral',c:'ink2'},{n:'Negative',c:'dneg'}],4,H-4,W-8,fs);
  const HB=H-lg.h-4,placed=[],cx=W/2,cy=HB/2+2;let s='';const ax=W/HB;
  const sent=v=>v>.35?'var(--dpos)':v>.08?'color-mix(in oklab,var(--dpos) 62%,var(--ink2))':v<-.35?'var(--dneg)':v<-.08?'color-mix(in oklab,var(--dneg) 62%,var(--ink2))':'var(--ink2)';
  ws.forEach((w,i)=>{const f=fmin+(fmax-fmin)*Math.sqrt((w.v-vmin)/((vmax-vmin)||1)),rot=o.rot&&i%3===1&&i>0,tw=String(w.t).length*f*.56+2,th=f*.86;
    const bw=rot?th:tw,bh=rot?tw:th;
    for(let k=0;k<1800;k++){const a=k*.32,r=.9*a;const x=cx+r*Math.cos(a)*ax*.62-bw/2,y=cy+r*Math.sin(a)*.62-bh/2;
      if(x<2||y<2||x+bw>W-2||y+bh>HB)continue;if(placed.some(p=>!(x+bw+2<p[0]||x>p[2]+2||y+bh+1<p[1]||y>p[3]+1)))continue;
      placed.push([x,y,x+bw,y+bh]);const c=o.color==='group'?col(w.g+1):sent(w.s),px=x+bw/2,py=y+bh/2;
      s+=`<text class="wd" data-i="${o.color==='group'?w.g:i}" x="${n1(px)}" y="${n1(py+f*.33)}" text-anchor="middle" font-size="${n1(f)}"${rot?` transform="rotate(-90 ${n1(px)} ${n1(py)})"`:''} style="fill:${c};animation-delay:${i*25}ms" data-t="${tipA(w.t,[[String(w.v),'Mentions',o.color==='group'?w.g+1:w.s>.08?'dpos':w.s<-.08?'dneg':'ink2']].concat(o.color==='group'?[[o.groups[w.g],'Topic','muted']]:[[w.s>.08?'Positive':w.s<-.08?'Negative':'Neutral','Sentiment','muted']]))}">${esc(w.t)}</text>`;break;}});
  return svgWrap(W,H,fs,`<g class="wds">${s}</g>`+lg.s);
}};

/* ======================= Calendar heatmap ======================= */
const XD0=Date.UTC(2025,0,1),XDN=['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
const xDate=k=>new Date(XD0+k*864e5);
E.cal={draw(o,st,W,H){
  const fs=FS(W),D=o.days,mx=Math.max(...D),q=v=>v<=0?0:Math.min(6,1+Math.floor(v/mx*5.999));
  const tok=k=>k?'s'+(k+1):'track';let s='',lab='';
  if(o.month==null){const L=fs*2.6,top=fs+6,bottom=fs+12,bg=fs+12,dayOf=m=>Math.round((Date.UTC(2025,m,1)-XD0)/864e5);
    let best=null;[1,2,3].forEach(k=>{const per=12/k,blocks=[...Array(k)].map((_,j)=>{const d0=dayOf(j*per),d1=j===k-1?D.length:dayOf((j+1)*per),off=(xDate(d0).getUTCDay()+6)%7;return {d0,d1,off,wk:Math.ceil((d1-d0+off)/7)};});
      const wk=Math.max(...blocks.map(b=>b.wk)),cs=Math.min((W-L-4)/wk,(H-top-bottom-(k-1)*bg)/(7*k),W>=560?26:15);if(!best||cs>best.cs+.5)best={k,blocks,wk,cs};});
    const {blocks,cs}=best,g=cs*.16,bh=cs*7+bg;
    blocks.forEach((b,j)=>{const y0=top+j*bh;
      for(let d=b.d0;d<b.d1;d++){const p=d-b.d0+b.off,wk=Math.floor(p/7),dw=p%7,v=D[d],dt=xDate(d),t=tok(q(v));
        s+=`<rect class="cl${q(v)?' gf':''}${kc(t)}" data-i="${dt.getUTCMonth()}" x="${n1(L+wk*cs)}" y="${n1(y0+dw*cs)}" width="${n1(cs-g)}" height="${n1(cs-g)}" rx="${n1(cs*.22)}" style="fill:var(--${t})" data-t="${tipA(XDN[dw]+' '+MON[dt.getUTCMonth()]+' '+dt.getUTCDate()+', 2025',[[fmt(v),o.vn||'Orders',t]])}"/>`;
        if(dt.getUTCDate()===1)lab+=`<text x="${n1(L+wk*cs+(dw>0?cs:0))}" y="${n1(y0-4)}" class="tk">${MON[dt.getUTCMonth()]}</text>`;}
      [0,2,4].forEach(dw=>{lab+=`<text x="${n1(L-5)}" y="${n1(y0+dw*cs+cs*.5+fs*.3)}" text-anchor="end" class="tk" font-size="${fs-1}">${XDN[dw]}</text>`;});});
    const sq=Math.min(cs*.8,11);let lx=W-4-6*(sq+2)-TW('More',fs)-4;lab+=`<text x="${n1(lx-4)}" y="${n1(H-4)}" text-anchor="end" class="tk">Less</text>`;for(let k=1;k<=6;k++){lab+=`<rect x="${n1(lx+(k-1)*(sq+2))}" y="${n1(H-4-sq)}" width="${n1(sq)}" height="${n1(sq)}" rx="2" style="fill:var(--s${k+1})"/>`;}lab+=`<text x="${n1(lx+6*(sq+2)+2)}" y="${n1(H-4)}" class="tk">More</text>`;
    lab+=`<text x="${n1(L)}" y="${n1(H-4)}" class="tk"><tspan class="tkb">${fmt(sumA(D))}</tspan> ${esc(o.vn?o.vn.toLowerCase():'orders')} in 2025</text>`;
  }else{const m=o.month,first=Date.UTC(2025,m,1),k0=Math.round((first-XD0)/864e5),nd=new Date(Date.UTC(2025,m+1,0)).getUTCDate(),dow0=(new Date(first).getUTCDay()+6)%7,rows=Math.ceil((nd+dow0)/7);
    const top=fs*2.8,cw=(W-8)/7,ch=(H-top-4)/rows;lab+=`<text x="4" y="${fs+2}" class="smt" font-size="${fs+2}">${MON[m]} 2025</text>`;
    XDN.forEach((d,i)=>{lab+=`<text x="${n1(4+cw*(i+.5))}" y="${n1(top-5)}" text-anchor="middle" class="tk">${W>=560?d:d[0]}</text>`;});
    const mv=D.slice(k0,k0+nd),mm=Math.max(...mv);
    for(let d=1;d<=nd;d++){const p=d-1+dow0,r=Math.floor(p/7),c=p%7,v=D[k0+d-1],lv=Math.min(6,1+Math.floor(v/mm*5.999)),t=tok(lv),x=4+c*cw,y=top+r*ch;
      s+=`<rect class="cl gf${kc(t)}" data-i="${c}" x="${n1(x+1.5)}" y="${n1(y+1.5)}" width="${n1(cw-3)}" height="${n1(ch-3)}" rx="5" style="fill:var(--${t})" data-t="${tipA(XDN[c]+' '+MON[m]+' '+d,[[fmt(v),o.vn||'Orders',t]])}"/>`;
      lab+=`<text x="${n1(x+6)}" y="${n1(y+fs+3)}" class="${lv>=4?'li'+ki(t):'tkn'}" font-size="${fs-1}">${d}</text>`;if(ch>fs*2.6&&cw>TW(fmt(v),fs)+6)lab+=`<text x="${n1(x+cw-6)}" y="${n1(y+ch-6)}" text-anchor="end" class="${lv>=4?'li'+ki(t):'tk2'}">${fmt(v)}</text>`;}}
  return svgWrap(W,H,fs,`<g class="gm">${s}</g>`+lab);
}};

/* ======================= Heat grid and punch card ======================= */
E.heatgrid={draw(o,st,W,H){
  const fs=FS(W),R_=o.rows,C=o.cols,M=o.m,mx=Math.max(...M.flat()),L=Math.max(...R_.map(r=>TW(r,fs)))+12,top=fs+8,cw=(W-L-4)/C.length,ch=(H-top-4)/R_.length;let s='',lab='';
  const every=Math.ceil(TW('00',fs)*1.6/cw);
  C.forEach((c,j)=>{if(j%every===0)lab+=`<text x="${n1(L+cw*(j+.5))}" y="${fs+1}" text-anchor="middle" class="tk">${esc(c)}</text>`;});
  R_.forEach((r,i)=>{lab+=`<text x="${n1(L-6)}" y="${n1(top+ch*(i+.5)+fs*.36)}" text-anchor="end" class="tkn">${esc(r)}</text>`;
    C.forEach((c,j)=>{const v=M[i][j],x=L+cw*j,y=top+ch*i,lv=Math.min(6,1+Math.floor(v/mx*5.999)),tt=` data-t="${tipA(r+' · '+c,[[fmt(v),o.vn||'Orders',o.punch?1:'s'+(lv+1)]])}"`;
      if(o.punch){const rr=Math.sqrt(v/mx)*Math.min(cw,ch)*.48;s+=`<rect class="hit" x="${n1(x)}" y="${n1(y)}" width="${n1(cw)}" height="${n1(ch)}"${tt}/><circle class="bub${kc(1)}" data-i="${i}" cx="${n1(x+cw/2)}" cy="${n1(y+ch/2)}" r="${n1(Math.max(.8,rr))}" style="fill:var(--c1);animation-delay:${(i*C.length+j)*4}ms"${tt}/>`;}
      else{const t='s'+(lv+1);s+=`<rect class="cl gf${kc(t)}" data-i="${i}" x="${n1(x+1)}" y="${n1(y+1)}" width="${n1(cw-2)}" height="${n1(ch-2)}" rx="${n1(Math.min(4,cw*.2))}" style="fill:var(--${t})"${tt}/>`;if(cw>TW(fmt(v),fs-1)+4&&ch>fs+2)lab+=`<text x="${n1(x+cw/2)}" y="${n1(y+ch/2+(fs-1)*.36)}" text-anchor="middle" class="${lv>=4?'li'+ki(t):'tk'}" font-size="${fs-1}">${fmt(v)}</text>`;}});});
  return svgWrap(W,H,fs,`<g class="gm">${s}</g>`+lab);
}};

/* ======================= Stream graph ======================= */
E.stream={draw(o,st,W,H){
  const fs=FS(W),cats=o.cats,S=o.series,n=S.length,m=cats.length,V=S.map(s=>s.v);
  const base=Array(m).fill(0);
  if(o.offset==='wiggle'){let y=0;for(let j=1;j<m;j++){let s1=0,s2=0;for(let i=0;i<n;i++){const a=V[i][j],b=V[i][j-1];let s3=(a-b)/2;for(let k=0;k<i;k++)s3+=V[k][j]-V[k][j-1];s1+=a;s2+=s3*a;}base[j-1]=y;if(s1)y-=s2/s1;}base[m-1]=y;
    const tot=cats.map((_,j)=>sumA(V.map(v=>v[j])));const shift=sumA(base.map((b,j)=>b+tot[j]/2))/m;for(let j=0;j<m;j++)base[j]-=shift;}
  else if(o.offset==='silhouette'){for(let j=0;j<m;j++)base[j]=-sumA(V.map(v=>v[j]))/2;}
  const layers=[];for(let i=0;i<n;i++){layers.push(cats.map((_,j)=>{const b=base[j]+sumA(V.slice(0,i).map(v=>v[j]));return [b,b+V[i][j]];}));}
  const lo=Math.min(...layers.flat().map(p=>p[0])),hi=Math.max(...layers.flat().map(p=>p[1]));
  const lg=legendSvg(S.map((s,i)=>({n:s.n,c:s.c||i+1})),4,fs+1,W-8,fs),top=lg.h+4,B=H-fs-8,L=4,R=W-4,x=j=>L+j*(R-L)/(m-1),y=v=>B-(v-lo)/((hi-lo)||1)*(B-top);let s='',lab='';
  layers.forEach((ly,i)=>{const t=ly.map((p,j)=>[x(j),y(p[1])]),b=ly.map((p,j)=>[x(j),y(p[0])]).reverse();const c=S[i].c||i+1;
    s+=`<path class="rbn st2${kc(c)}" data-i="${i}" d="${monoPath(t)}${monoPath(b).replace('M','L')}Z" style="fill:${col(c)}" data-t="${tipA(S[i].n,[[fmt(sumA(V[i]),o.u),'Total',c],[fmt(Math.max(...V[i]),o.u),'Peak month','muted']])}"/>`;
    let bj=0,bt=0;ly.forEach((p,j)=>{const th=y(p[0])-y(p[1]);if(th>bt&&j>0&&j<m-1){bt=th;bj=j;}});const tw=TW(S[i].n,fs-1);
    if(bt>fs+3&&x(bj)-tw/2>L&&x(bj)+tw/2<R)lab+=`<text x="${n1(x(bj))}" y="${n1((y(ly[bj][0])+y(ly[bj][1]))/2+(fs-1)*.36)}" text-anchor="middle" class="li${ki(c)}" font-size="${fs-1}">${esc(S[i].n)}</text>`;});
  const every=Math.ceil(m/(W>=560?12:6));cats.forEach((c,j)=>{if(j%every===0)lab+=`<text x="${n1(x(j))}" y="${n1(H-3)}" text-anchor="${j===0?'start':'middle'}" class="tk">${esc(c)}</text>`;});
  return svgWrap(W,H,fs,`<g class="gm">${s}</g>`+lab+lg.s);
}};

/* ======================= Candlestick (zoom + brush) ======================= */
E.candle={draw(o,st,W,H){
  const fs=FS(W),Dall=o.data,NN=Dall.length;let a=0,b=NN;if(st.z){a=Math.max(0,Math.floor(st.z[0]*NN+1e-6));b=Math.min(NN,Math.max(a+5,Math.ceil(st.z[1]*NN-1e-6)));}
  const D=Dall.slice(a,b),n=D.length,ma=o.ma?Dall.map((_,k)=>k<o.ma-1?null:sumA(Dall.slice(k-o.ma+1,k+1).map(d=>d.c))/o.ma).slice(a,b):null;
  const lo=Math.min(...D.map(d=>d.l)),hi=Math.max(...D.map(d=>d.h)),lw=xYw(lo,hi,o.u,fs),L=lw,R=W-6,top=o.ma?fs+8:6,B=H-fs-10,vh=o.vol?(B-top)*.22:0,pB=B-vh-(o.vol?6:0);
  const ax=xYax(lo,hi,L,R,top,pB,fs,o.u,4),y=ax.y,bw=(R-L)/n;let s='',vol='',lab='',hov='';const vmax=o.vol?Math.max(...D.map(d=>d.v)):1;
  D.forEach((d,k)=>{const cx=L+bw*(k+.5),up=d.c>=d.o,c=up?'good':'crit',w=Math.max(1,bw*.64);
    s+=`<g class="cdl${up?' up':' dn'}" data-i="${k}"><line class="wk" x1="${n1(cx)}" x2="${n1(cx)}" y1="${n1(y(d.h))}" y2="${n1(y(d.l))}" style="stroke:${col(c)}"/><rect class="cbody gf${kc(c)}" x="${n1(cx-w/2)}" y="${n1(y(Math.max(d.o,d.c)))}" width="${n1(w)}" height="${n1(Math.max(1,Math.abs(y(d.o)-y(d.c))))}" rx="${w>4?1:0}" style="fill:${col(c)}"/></g>`;
    if(o.vol){const h=d.v/vmax*vh;vol+=`<rect class="vb" x="${n1(cx-w/2)}" y="${n1(B-h)}" width="${n1(w)}" height="${n1(h)}" style="fill:${col(c)}"/>`;}
    hov+=`<rect class="hit" x="${n1(L+bw*k)}" y="${n1(top)}" width="${n1(bw)}" height="${n1(B-top)}" data-t="${tipA(d.d,[[fmt(d.o,o.u),'Open','muted'],[fmt(d.h,o.u),'High','muted'],[fmt(d.l,o.u),'Low','muted'],[fmt(d.c,o.u),'Close',c]].concat(o.vol?[[fmt(d.v),'Volume','muted']]:[]).concat(ma&&ma[k]!=null?[[fmt(ma[k],o.u),o.ma+'-day average',1]]:[]))}"/>`;});
  if(ma){const pts=ma.map((v,k)=>v==null?null:[L+bw*(k+.5),y(v)]).filter(Boolean);if(pts.length>1)lab+=`<path class="ln mal" d="${monoPath(pts)}" style="stroke:var(--c1)" stroke-width="2"/>`;lab+=legendSvg([{n:o.ma+'-day moving average',c:1,t:'line'},{n:'Up day',c:'good'},{n:'Down day',c:'crit'}],L,fs,R-L,fs).s;}
  const every=Math.max(1,Math.ceil(n/(W>=560?9:5)));D.forEach((d,k)=>{if(k%every===0)lab+=`<text x="${n1(L+bw*(k+.5))}" y="${n1(B+fs+4)}" text-anchor="middle" class="tk">${esc(d.d)}</text>`;});
  if(o.vol)lab+=`<text x="${n1(L+3)}" y="${n1(B-vh-1)}" class="tk" font-size="${fs-1}">Volume</text>`;
  return svgWrap(W,H,fs,ax.g+`<g class="gm">${s}</g><g class="vols">${vol}</g>`+lab+hov,`data-pl="${n1(L)}" data-pr="${n1(R)}" data-pt="${n1(top)}" data-pb="${n1(B)}" data-n="${n}" data-z0="${a}" data-nn="${NN}"`);
}};

/* ======================= Timeline slicer ======================= */
E.timeline={draw(o,st,W,H){
  const fs=FS(W),Mn=o.months,vals=o.v,g=st.gran||o.gran||'month',sel=st.sel||o.sel;const big=W>=560;
  const per=g==='year'?12:g==='quarter'?3:1,np=Math.ceil(Mn.length/per),lab0=k=>{const m=k*per;const yr=2024+Math.floor(m/12);return g==='year'?String(yr):g==='quarter'?'Q'+(Math.floor((m%12)/3)+1):MON[m%12];};
  const btn=xBtns([['year','Year'],['quarter','Quarter'],['month','Month']].map(([k,t])=>({k:'gran:'+k,t})),'gran:'+g,0,0,fs-1);
  const L=4,R=W-4,top=big?fs*2+20:fs+22,ch=big?40:26,cw=(R-L)/np;let s='',lab='';
  const a=sel[0],b=sel[1],fmtM=m=>MON[m%12]+' '+(2024+Math.floor(m/12));
  lab+=`<text x="${L}" y="${fs+3}" class="smt" font-size="${fs+1}">${fmtM(a)} – ${fmtM(b)} <tspan class="tk" font-weight="500">· ${b-a+1} months</tspan></text>`;if(big)lab+=`<text x="${L}" y="${n1(fs*2+8)}" class="tk">Click a ${g}, then another to set a range</text>`;
  for(let k=0;k<np;k++){const m0=k*per,m1=m0+per-1,on=m1>=a&&m0<=b,x=L+cw*k;
    s+=`<g class="tlc${on?' on':''}" data-act="pick:${m0}-${m1}" role="button" aria-pressed="${on}"><rect class="${on?'gf k-c1 tlon':'tloff'}" x="${n1(x+1)}" y="${n1(top)}" width="${n1(cw-2)}" height="${ch}" rx="4" style="${on?'fill:var(--c1)':''}"/><text x="${n1(x+cw/2)}" y="${n1(top+ch/2+(fs-1)*.36)}" text-anchor="middle" class="${on?'li ki-c1':'tkn'}" font-size="${fs-1}">${cw>TW(lab0(k),fs-1)+2?lab0(k):lab0(k)[0]}</text></g>`;
    if(g!=='year'&&m0%12===0)lab+=`<text x="${n1(x+2)}" y="${n1(top-5)}" class="tkb" font-size="${fs-1}">${2024+m0/12}</text>`;}
  /* handles */
  const xa=L+cw*Math.floor(a/per),xb=L+cw*(Math.floor(b/per)+1);s+=`<rect class="tlh" x="${n1(xa-2)}" y="${n1(top-3)}" width="4" height="${ch+6}" rx="2"/><rect class="tlh" x="${n1(xb-2)}" y="${n1(top-3)}" width="4" height="${ch+6}" rx="2"/>`;
  /* filtered preview: monthly sales with selection highlighted */
  const pt=top+ch+fs+10,pb=H-4,mx=Math.max(...vals),bw=(R-L)/Mn.length;let pv='';
  vals.forEach((v,k)=>{const on=k>=a&&k<=b,h=(pb-pt)*v/mx;pv+=`<rect class="${on?'m'+kc(1):'tlm'}" x="${n1(L+bw*k+1)}" y="${n1(pb-h)}" width="${n1(bw-2)}" height="${n1(h)}" rx="1.5" style="${on?'fill:var(--c1)':''}" data-t="${tipA(fmtM(k),[[fmt(v,'$'),'Sales',on?1:'muted']])}"/>`;});
  const tot=sumA(vals.slice(a,b+1));lab+=`<text x="${n1(R)}" y="${n1(pt-3)}" text-anchor="end" class="tk"><tspan class="tkb">${fmt(tot,'$')}</tspan> sales in range</text>`;
  return svgWrap(W,H,fs,`<g class="gm">${s}${pv}</g>`+lab+`<g transform="translate(${n1(R-btn.w)},2)">${btn.s}</g>`);
},act(o,st,verb,arg){
  if(verb==='gran'){st.gran=arg;st.anchor=null;return true;}
  if(verb==='pick'){const [m0,m1]=arg.split('-').map(Number);const A=st.anchor;if(!A){st.sel=[m0,m1];st.anchor=[m0,m1];}else{st.sel=[Math.min(A[0],m0),Math.max(A[1],m1)];st.anchor=null;}return true;}}};

/* ======================= Liquid fill gauge ======================= */
E.liquid={draw(o,st,W,H){
  const fs=FS(W),items=o.items||[{n:o.n,v:o.v,c:o.c}],n=items.length,cw=W/n;let s='',defs='',lab='';
  items.forEach((it,j)=>{const R=Math.min(cw/2-(W>=560?20:6),(H-fs*2.4)/2-4),cx=cw*(j+.5),cy=(H-fs*2)/2+2,lvl=cy+R-2*R*it.v,A=R*.07,lam=R*1.3,c=it.c||1;
    const id='lq'+(++UID);defs+=`<clipPath id="${id}"><circle cx="${n1(cx)}" cy="${n1(cy)}" r="${n1(R*.9)}"/></clipPath>`;
    const wave=(ph,yy)=>{let d=`M${n1(cx-R-lam*2)},${n1(H)}`;for(let x=-R-lam*2;x<=R+lam*2;x+=lam/8)d+=`L${n1(cx+x)},${n1(yy+A*Math.sin((x/lam+ph)*Math.PI*2))}`;return d+`L${n1(cx+R+lam*2)},${n1(H)}Z`;};
    s+=`<circle class="lqo" cx="${n1(cx)}" cy="${n1(cy)}" r="${n1(R)}" style="stroke:${col(c)}"/><circle class="lqbg" cx="${n1(cx)}" cy="${n1(cy)}" r="${n1(R*.9)}"/>`;
    s+=`<g clip-path="url(#${id})" data-i="${j}" data-t="${tipA(it.n,[[Math.round(it.v*100)+'%',o.vn||'of goal',c]])}"><path class="lqw2" d="${wave(.5,lvl+2)}" style="fill:${col(c)};--lam:${n1(lam)}px"/><path class="lqw gf${kc(c)}" d="${wave(0,lvl)}" style="fill:${col(c)};--lam:${n1(lam)}px"/></g>`;
    const id2='lt'+(++UID),fz=Math.min(R*.5,fs*3.4);defs+=`<clipPath id="${id2}"><rect x="${n1(cx-R)}" y="${n1(lvl)}" width="${n1(R*2)}" height="${n1(R*2)}"/></clipPath>`;
    const t=`${Math.round(it.v*100)}<tspan font-size="${n1(fz*.5)}">%</tspan>`;
    lab+=`<text x="${n1(cx)}" y="${n1(cy+fz*.34)}" text-anchor="middle" class="cv lqt" font-size="${n1(fz)}">${t}</text><text x="${n1(cx)}" y="${n1(cy+fz*.34)}" text-anchor="middle" class="cv lqt2${ki(c)}" font-size="${n1(fz)}" clip-path="url(#${id2})">${t}</text>`;
    lab+=`<text x="${n1(cx)}" y="${n1(cy+R+fs+6)}" text-anchor="middle" class="lbt" font-weight="600">${esc(it.n)}</text>`;if(it.sub)lab+=`<text x="${n1(cx)}" y="${n1(cy+R+fs*2+8)}" text-anchor="middle" class="tk" font-size="${fs-1}">${esc(it.sub)}</text>`;});
  return svgWrap(W,H,fs,`<defs>${defs}</defs><g class="gm">${s}</g>`+lab);
}};

/* ======================= Radial bars ======================= */
E.radial={draw(o,st,W,H){
  const fs=FS(W);let s='',lab='';
  let g0='';
  if(o.mode!=='columns'){const it=o.items,n=it.length,R=Math.min(H/2-6,W*.3),cx=W-R-(W>=560?40:8),cy=H/2,rw=R*.62/n,gap=rw*.18,lx=W>=560?40:8;
    it.forEach((d,i)=>{const r=R-i*rw-rw/2,c=d.c||i+1,f=Math.min(d.v,1),a0=-Math.PI/2,a1=a0+Math.PI*2*f-.0001,lg=f>.5?1:0;
      s+=`<circle class="rtk" cx="${n1(cx)}" cy="${n1(cy)}" r="${n1(r)}" stroke-width="${n1(rw-gap)}"/>`;
      s+=`<path class="rar${kc(c)}" data-i="${i}" d="M${xP(cx,cy,r,a0)}A${n1(r)},${n1(r)} 0 ${lg},1 ${xP(cx,cy,r,a1)}" stroke-width="${n1(rw-gap)}" style="stroke:${col(c)};animation-delay:${i*120}ms" pathLength="1" data-t="${tipA(d.n,[[Math.round(d.v*100)+'%','of target',c],[d.sub||'','','muted']])}"/>`;
      const ly=H/2-(n*(fs*2.7))/2+i*fs*2.7+fs;lab+=`<circle cx="${n1(lx+5)}" cy="${n1(ly-fs*.36)}" r="5" style="fill:${col(c)}"/><text x="${n1(lx+16)}" y="${n1(ly)}" class="lbt" font-weight="600">${esc(d.n)} <tspan class="tkb">${Math.round(d.v*100)}%</tspan></text>`+(d.sub?`<text x="${n1(lx+16)}" y="${n1(ly+fs+1)}" class="tk" font-size="${fs-1}">${esc(d.sub)}</text>`:'');});}
  else{const cats=o.cats,v=o.v,n=cats.length,mx=Math.max(...v),cx=W/2,cy=H/2,R=Math.min(H/2-fs-4,W/2-24),r0=R*.3,step=Math.PI*2/n;
    for(let l=1;l<=3;l++)g0+=`<circle class="rg" cx="${n1(cx)}" cy="${n1(cy)}" r="${n1(r0+(R-r0)*l/3)}"/>`;
    v.forEach((x,k)=>{const a0=-Math.PI/2+k*step+step*.14,a1=-Math.PI/2+(k+1)*step-step*.14,r=r0+(R-r0)*x/mx,t='s'+(3+Math.round(x/mx*4));
      s+=`<path class="sl${kc(t)}" data-i="${k}" d="${xSect(cx,cy,r0,r,a0,a1)}" style="fill:var(--${t});animation-delay:${k*40}ms" data-t="${tipA(cats[k],[[fmt(x,o.u),o.vn||'Sales',t]])}"/>`;
      const m=(a0+a1)/2,cs=Math.cos(m);lab+=`<text x="${n1(cx+(R+6)*cs)}" y="${n1(cy+(R+6)*Math.sin(m)+fs*.36)}" text-anchor="${Math.abs(cs)<.3?'middle':cs>0?'start':'end'}" class="tk">${esc(cats[k])}</text>`;});
    lab+=`<text x="${n1(cx)}" y="${n1(cy+fs*.2)}" text-anchor="middle" class="cv" font-size="${n1(Math.min(r0*.5,fs*1.8))}">${fmt(sumA(v),o.u)}</text><text x="${n1(cx)}" y="${n1(cy+fs*1.3)}" text-anchor="middle" class="tk" font-size="${fs-1}">${esc(o.cl||'Total')}</text>`;}
  return svgWrap(W,H,fs,g0+`<g class="gm">${s}</g>`+lab);
}};

/* ======================= Tachometer ======================= */
E.tacho={draw(o,st,W,H){
  const fs=FS(W),mn=o.min||0,mx=o.max,cx=W/2,R=Math.min(W/2-(W>=560?40:24),H*.58),cy=Math.min(H*.6,R+fs+6),a=v=>Math.PI*5/6+(v-mn)/(mx-mn)*Math.PI*4/3,rw=R*.17;let s='',lab='';
  const arc=(v0,v1,r1,r2,c,cls,i)=>`<path class="${cls}${kc(c)}"${i!=null?` data-i="${i}"`:''} d="${xSect(cx,cy,r1,r2,a(v0),a(v1))}" style="fill:${col(c)}"/>`;
  if(o.bands){let p=mn;o.bands.forEach((b,i)=>{s+=arc(p,b.to,R-rw,R,b.c,'tb3 sl',i).replace('/>',` data-t="${tipA(b.n,[[fmt(p,o.u)+' – '+fmt(b.to,o.u),'Range',b.c]])}"/>`);p=b.to;});}
  else{s+=arc(mn,mx,R-rw,R,'track','tb3');const steps=24;for(let k=0;k<steps;k++){const v0=mn+(mx-mn)*k/steps,v1=mn+(mx-mn)*(k+1)/steps;if(v0>=o.v)break;s+=arc(v0,Math.min(v1,o.v)+(mx-mn)*.002,R-rw,R,'s'+(2+Math.round(k/steps*5)),'tb3 sl');}}
  const T=ticks(mn,mx,W>=560?10:5);T.t.forEach(t=>{const an=a(t);s+=`<line class="ttk" x1="${n1(cx+(R-rw-2)*Math.cos(an))}" y1="${n1(cy+(R-rw-2)*Math.sin(an))}" x2="${n1(cx+(R-rw-6)*Math.cos(an))}" y2="${n1(cy+(R-rw-6)*Math.sin(an))}"/>`;lab+=`<text x="${n1(cx+(R-rw-8-fs*.8)*Math.cos(an))}" y="${n1(cy+(R-rw-8-fs*.8)*Math.sin(an)+fs*.36)}" text-anchor="middle" class="tk" font-size="${fs-1}">${fmt(t,o.u==='$'?'':o.u)}</text>`;});
  if(o.target!=null){const an=a(o.target);s+=`<path class="ttg" d="M${xP(cx,cy,R+2,an)}L${xP(cx,cy,R+10,an-.06)}L${xP(cx,cy,R+10,an+.06)}Z"/>`;const tt='Target '+fmt(o.target,o.u),tx=cx+(R+14)*Math.cos(an),tw=TW(tt,fs-1),right=Math.cos(an)>0,fit=right?tx+tw<W-2:tx-tw>2;lab+=`<text x="${n1(fit?tx:right?W-2:2)}" y="${n1(cy+(R+14)*Math.sin(an)-(fit?0:fs+2))}" text-anchor="${right?(fit?'start':'end'):(fit?'end':'start')}" class="tk" font-size="${fs-1}">${tt}</text>`;}
  const an=a(o.v),nl=R-rw*.4;s+=`<g class="ndl" data-t="${tipA(o.n,[[fmt(o.v,o.u),'Value',1]].concat(o.target!=null?[[fmt(o.target,o.u),'Target','ink']]:[]))}"><path class="ndp" d="M${xP(cx,cy,nl,an)}L${xP(cx,cy,R*.07,an+Math.PI/2)}L${xP(cx,cy,R*.12,an+Math.PI)}L${xP(cx,cy,R*.07,an-Math.PI/2)}Z"/><circle class="ndh sph k-ink" cx="${n1(cx)}" cy="${n1(cy)}" r="${n1(R*.09)}"/></g>`;
  lab+=`<text x="${n1(cx)}" y="${n1(cy+R*.42)}" text-anchor="middle" class="cv" font-size="${n1(Math.min(R*.3,fs*2.6))}">${fmt(o.v,o.u)}</text><text x="${n1(cx)}" y="${n1(cy+R*.42+fs*1.4)}" text-anchor="middle" class="tk">${esc(o.n)}</text>`;
  return svgWrap(W,H,fs,`<g class="gm">${s}</g>`+lab);
}};

/* ======================= Ticker / scroller (HTML) ======================= */
E.ticker={draw(o,st,W,H){
  const item=d=>`<span class="tki"><b>${esc(d.l)}</b><span>${esc(d.v)}</span>${d.d!=null?`<i class="${(d.inv?-d.d:d.d)>=0?'up':'down'}">${d.d>=0?'▲':'▼'} ${Math.abs(d.d).toFixed(1)}%</i>`:''}</span>`;
  if(o.mode==='v')return H_('tkv',`<div class="tkv-h"><span class="tkv-dot"></span>${esc(o.title||'Live updates')}</div><div class="tkv-win"><div class="tkv-track">${o.items.concat(o.items).map(d=>`<div class="tkv-r"><span class="tkv-t">${esc(d.t)}</span><span class="tkv-x">${esc(d.x)}</span></div>`).join('')}</div></div>`);
  const row=o.items.map(item).join('<span class="tks" aria-hidden="true">•</span>');
  return H_('tkr',`<div class="tkr-h">${esc(o.title||'Today')}</div><div class="tkr-win"><div class="tkr-track"><div class="tkr-run">${row}<span class="tks" aria-hidden="true">•</span></div><div class="tkr-run" aria-hidden="true">${row}<span class="tks">•</span></div></div></div><div class="tkr-sub">${o.items.slice(0,3).map(d=>`<div class="tkr-c"><span>${esc(d.l)}</span><b>${esc(d.v)}</b>${spark(d.tr||TY,{w:120,h:28,c:1})}</div>`).join('')}</div>`);
}};

/* ======================= Deneb (Vega-Lite) ======================= */
const xJson=s=>esc(s).replace(/(&quot;[^&]*?&quot;)(\s*:)/g,'<i class="jk">$1</i>$2').replace(/:\s*(&quot;[^&]*?&quot;)/g,': <i class="js">$1</i>').replace(/([:\[,]\s*)(-?\d+\.?\d*)/g,'$1<i class="jn">$2</i>');
E.deneb={draw(o,st,W,H){
  const big=W>=560,vw=big?Math.round(W*.6):Math.round(W*.58),vh=H-8;let svg='';const fs=FS(W)-(big?0:1);
  if(o.mode==='ridge'){const ms=o.rows,n=ms.length,L=TW('Mmm',fs)+8,R=vw-6,top=10,B=vh-fs-8,rh=(B-top)/(n+1.4);const all=ms.flatMap(m=>m.v),lo=Math.min(...all),hi=Math.max(...all),x=v=>L+(v-lo)/(hi-lo)*(R-L);
    const K=ms.map(m=>xKde(m.v,lo,hi,40)),dm=Math.max(...K.flat().map(p=>p[1]));let s='',lab='';
    ms.forEach((m,i)=>{const base=top+rh*(i+1.4),pts=K[i].map(p=>[x(p[0]),base-p[1]/dm*rh*2.2]);const t='s'+(2+Math.round(i/(n-1)*5));
      s+=`<path class="rdg gf${kc(t)}" data-i="${i}" d="M${n1(L)},${n1(base)}L${pts.map(p=>n1(p[0])+','+n1(p[1])).join('L')}L${n1(R)},${n1(base)}Z" style="fill:var(--${t})" data-t="${tipA(m.n,[[fmt(xStats(m.v).md),'Median orders a day',t]])}"/>`;lab+=`<text x="${n1(L-5)}" y="${n1(base-1)}" text-anchor="end" class="tk" font-size="${fs-1}">${m.n}</text>`;});
    const T=ticks(lo,hi,4);T.t.filter(t=>t>=lo&&t<=hi).forEach(t=>{lab+=`<text x="${n1(x(t))}" y="${n1(vh-3)}" text-anchor="middle" class="tk" font-size="${fs-1}">${fmt(t)}</text>`;});
    svg=svgWrap(vw,vh,fs,`<g class="gm">${s}</g>`+lab);}
  else if(o.mode==='layer'){const v=o.v,cats=o.cats,n=v.length,L=xYw(0,Math.max(...v),'$',fs),R=vw-4,top=fs+6,B=vh-fs-8,ax=xYax(0,Math.max(...v),L,R,top,B,fs,'$',4),bw=(R-L)/n,avg=sumA(v)/n;let s='',lab='';
    v.forEach((x,k)=>{const above=x>=avg,c=above?1:'muted-mark';s+=`<path class="m${kc(c)}" data-i="${k}" d="${bp(L+bw*k+bw*.16,ax.y(x),bw*.68,B-ax.y(x),2,'t')}" style="fill:${col(c)}" data-t="${tipA(cats[k],[[fmt(x,'$'),'Sales',c],[above?'Above average':'Below average','','muted']])}"/>`;if(bw>TW(cats[k],fs-1)||k%2===0)lab+=`<text x="${n1(L+bw*(k+.5))}" y="${n1(B+fs+3)}" text-anchor="middle" class="tk" font-size="${fs-1}">${cats[k]}</text>`;});
    const ya=n1(ax.y(avg));lab+=`<line class="ref" x1="${n1(L)}" x2="${n1(R)}" y1="${ya}" y2="${ya}"/><text x="${n1(R)}" y="${n1(ax.y(avg)-4)}" text-anchor="end" class="reft" font-size="${fs-1}">Average ${fmt(avg,'$')}</text>`;
    svg=svgWrap(vw,vh,fs,ax.g+`<g class="gm">${s}</g>`+lab);}
  else{const S=o.series,cats=o.cats,sel=st.sel==null?null:+st.sel,all=S.flatMap(s=>s.v),L=xYw(0,Math.max(...all),'$',fs),R=vw-4,top=fs*2+8,B=vh-fs-8,ax=xYax(0,Math.max(...all),L,R,top,B,fs,'$',4),x=k=>L+k*(R-L)/(cats.length-1);let s='',lab='';
    S.forEach((sr,i)=>{const c=sel!=null&&sel!==i?'muted-mark':i+1,pts=sr.v.map((v,k)=>[x(k),ax.y(v)]);s+=`<path class="ln" d="${monoPath(pts)}" style="stroke:${col(c)}" stroke-width="${sel===i?3:2}"/>`;});
    let lx=L;S.forEach((sr,i)=>{const w=TW(sr.n,fs-1)+24;lab+=`<g class="sbtn${sel===i?' on':''}" data-act="sel:${i}" role="button" aria-pressed="${sel===i}"><rect x="${n1(lx)}" y="2" width="${n1(w)}" height="${fs+8}" rx="${(fs+8)/2}"/><circle cx="${n1(lx+9)}" cy="${n1(2+(fs+8)/2)}" r="3.5" style="fill:${col(i+1)}"/><text x="${n1(lx+16)}" y="${n1(2+(fs+8)/2+(fs-1)*.36)}" font-size="${fs-1}">${esc(sr.n)}</text></g>`;lx+=w+4;});
    cats.forEach((c,k)=>{if(k%2===0)lab+=`<text x="${n1(x(k))}" y="${n1(B+fs+3)}" text-anchor="middle" class="tk" font-size="${fs-1}">${c}</text>`;});
    svg=svgWrap(vw,vh,fs,ax.g+`<g class="gm">${s}</g>`+lab);}
  return H_('dnb',`<div class="dnb-code"><div class="dnb-h"><span>Vega-Lite</span><span>Deneb</span></div><pre>${xJson(o.spec)}</pre></div><div class="dnb-viz">${svg}</div>`);
},act(o,st,verb,arg){if(verb==='sel'){st.sel=st.sel!=null&&+st.sel===+arg?null:+arg;return true;}}};

/* ======================= SVG measures in a table (HTML) ======================= */
E.svgtable={draw(o,st,W,H){
  const rows=o.rows,mx=Math.max(...rows.map(r=>r.v));
  const bullet=r=>{const w=100,h=14,x=v=>v/(r.t*1.25)*w;return `<svg class="svb" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true"><rect x="0" y="3" width="${w}" height="8" rx="2" class="svb0"/><rect x="0" y="5" width="${n1(Math.min(w,x(r.v)))}" height="4" rx="1" style="fill:${r.v>=r.t?'var(--good)':'var(--crit)'}"/><rect x="${n1(x(r.t)-.8)}" y="1.5" width="1.6" height="11" class="svb1"/></svg>`;};
  const head=o.mode==='pill'?['Product','Sales','Progress to goal','Status']:['Product','Sales','12-month trend','vs target','Margin'];
  const body=rows.map((r,i)=>{const pg=Math.min(1.2,r.v/r.t);
    if(o.mode==='pill'){const stt=pg>=1?['good','On track','●']:pg>=.9?['warn','At risk','▲']:['crit','Behind','◆'];return `<tr data-i="${i}"><td class="tl">${esc(r.n)}</td><td>${fmt(r.v,'$')}</td><td><div class="pill2"><div class="pill2-f" style="width:${Math.min(100,pg*100).toFixed(0)}%;background:var(--${stt[0]})"></div><span>${Math.round(pg*100)}%</span></div></td><td><span class="stt s-${stt[0]}"><i aria-hidden="true">${stt[2]}</i>${stt[1]}</span></td></tr>`;}
    return `<tr data-i="${i}"><td class="tl">${esc(r.n)}</td><td>${fmt(r.v,'$')}</td><td class="sv">${spark(r.tr,{w:100,h:22,c:1,area:false})}</td><td class="sv">${bullet(r)}</td><td><div class="dbar"><b><i style="width:${(r.m/Math.max(...rows.map(q=>q.m))*100).toFixed(0)}%"></i></b><span>${r.m.toFixed(1)}%</span></div></td></tr>`;}).join('');
  return H_('svt',`<table class="tbl svt-t"><thead><tr>${head.map((h,i)=>`<th class="${i?'':'tl'}">${h}</th>`).join('')}</tr></thead><tbody>${body}</tbody></table>`);
}};

/* ======================= HTML Content (HTML) ======================= */
E.htmlc={draw(o,st,W,H){
  if(o.mode==='text'){const t=o.t;return H_('htx',`<div class="htx-in"><p class="htx-k">${esc(t.k)}</p><p class="htx-p">Sales reached <b class="hv1">${t.s}</b>, <b class="hv2 up">▲ ${t.g}</b> on last year. <b class="hv1">${t.top}</b> led with <b class="hv1">${t.topv}</b>, while <b class="hv3">${t.weak}</b> slipped <b class="hv2 down">▼ ${t.weakv}</b>.</p><div class="htx-bar" aria-hidden="true">${o.parts.map((p,i)=>`<i style="flex:${p.v};background:var(--c${i+1})" title="${esc(p.n)}"></i>`).join('')}</div><div class="htx-lg">${o.parts.map((p,i)=>`<span><i style="background:var(--c${i+1})"></i>${esc(p.n)} ${Math.round(p.v/sumA(o.parts.map(q=>q.v))*100)}%</span>`).join('')}</div></div>`);}
  return H_('htc',o.cards.map((c,i)=>`<div class="htc-c" data-i="${i}" style="--k:var(--c${i+1})"><div class="htc-top"><span class="htc-ic ki-c${i+1}">${ic(c.ic)}</span><span class="htc-l">${esc(c.l)}</span></div><div class="htc-v">${esc(c.v)}</div><div class="htc-f"><span class="htc-d ${c.d>=0?'up':'down'}">${c.d>=0?'▲':'▼'} ${Math.abs(c.d).toFixed(1)}%</span><span class="htc-s">${esc(c.s)}</span></div><div class="htc-spk">${spark(c.tr,{w:160,h:30,c:i+1})}</div></div>`).join(''));
}};
