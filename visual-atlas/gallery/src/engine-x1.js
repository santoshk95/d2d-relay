/* ============================================================
   Extended visuals I — flow, network, hierarchy, statistics and
   comparison. Same contract as the built-in renderers:
   draw(o, st, W, H) returns SVG markup; act() handles in-chart
   controls and returns true (or 'drill') to re-render.
   ============================================================ */
function xYax(lo,hi,L,R,top,B,fs,u,n){
  const T=ticks(lo,hi,n||4);const y=v=>B-(v-T.lo)/((T.hi-T.lo)||1)*(B-top);let g='';
  T.t.forEach(t=>{const yy=n1(y(t));g+=`<line class="${t===0?'bl':'gl'}" x1="${n1(L)}" x2="${n1(R)}" y1="${yy}" y2="${yy}"/><text x="${n1(L-6)}" y="${n1(yy+fs*.36)}" text-anchor="end" class="tk">${fmt(t,u)}</text>`;});
  return {g,y,T};
}
const xYw=(lo,hi,u,fs,n)=>{const T=ticks(lo,hi,n||4);return Math.max(...T.t.map(t=>TW(fmt(t,u),fs)))+10;};
function xXax(lo,hi,L,R,top,B,fs,u,n){
  const T=ticks(lo,hi,n||5);const x=v=>L+(v-T.lo)/((T.hi-T.lo)||1)*(R-L);let g='';
  T.t.forEach(t=>{const xx=n1(x(t));g+=`<line class="${t===0?'bl':'gl'}" x1="${xx}" x2="${xx}" y1="${n1(top)}" y2="${n1(B)}"/><text x="${xx}" y="${n1(B+fs+4)}" text-anchor="middle" class="tk">${fmt(t,u)}</text>`;});
  return {g,x,T};
}
const xRp=(lo,hi,u,fs,n)=>{const T=ticks(lo,hi,n||5);return Math.max(10,TW(fmt(T.hi,u),fs)/2+4);};
const xQ=(s,p)=>{const i=(s.length-1)*p,a=Math.floor(i),b=Math.ceil(i);return s[a]+(s[b]-s[a])*(i-a);};
function xStats(v){
  const s=v.slice().sort((a,b)=>a-b),q1=xQ(s,.25),md=xQ(s,.5),q3=xQ(s,.75),iqr=q3-q1;
  const lo=s.find(x=>x>=q1-1.5*iqr),hi=s.slice().reverse().find(x=>x<=q3+1.5*iqr),mean=sumA(s)/s.length;
  const sd=Math.sqrt(sumA(s.map(x=>(x-mean)*(x-mean)))/Math.max(1,s.length-1));
  return {s,q1,md,q3,lo,hi,mean,sd,out:s.filter(x=>x<lo||x>hi),n:s.length,min:s[0],max:s[s.length-1]};
}
function xKde(v,lo,hi,n){
  const S=xStats(v);const h=(1.06*S.sd*Math.pow(v.length,-.2))||1;const out=[];
  for(let k=0;k<=n;k++){const x=lo+(hi-lo)*k/n;let d=0;for(const a of v){const z=(x-a)/h;d+=Math.exp(-.5*z*z);}out.push([x,d/(v.length*h*2.5066)]);}
  return out;
}
/* small in-chart toggle buttons: [{k:'bins:8',t:'8'}] */
function xBtns(items,on,x,y,fs){
  let s='',cx=x;const h=fs+8;
  items.forEach(it=>{const w=TW(it.t,fs)+14;const sel=it.k===on;s+=`<g class="sbtn${sel?' on':''}" data-act="${it.k}" role="button" aria-pressed="${sel}"><rect x="${n1(cx)}" y="${n1(y)}" width="${n1(w)}" height="${h}" rx="${h/2}"/><text x="${n1(cx+w/2)}" y="${n1(y+h/2+fs*.36)}" text-anchor="middle">${esc(it.t)}</text></g>`;cx+=w+3;});
  return {s,w:cx-x};
}
const xInit=n=>String(n).split(/\s+/).map(w=>w[0]).join('').slice(0,2).toUpperCase();
/* place labels top to bottom without overlap; items {y,h} -> adjusted y */
function xSpread(items,gap,lo,hi){
  items.sort((a,b)=>a.y-b.y);let last=-1e9;items.forEach(it=>{it.y=Math.max(it.y,last+gap);last=it.y;});
  const ov=items.length?items[items.length-1].y-hi:0;if(ov>0){items.forEach(it=>{it.y-=ov;});for(let i=items.length-2;i>=0;i--)if(items[i].y>items[i+1].y-gap)items[i].y=items[i+1].y-gap;}
  if(items.length&&items[0].y<lo){const d=lo-items[0].y;items.forEach(it=>{it.y+=d;});}
  return items;
}

/* ======================= Sankey ======================= */
E.sankey={draw(o,st,W,H){
  const fs=FS(W),N=o.nodes.map((d,i)=>({...d,i,inL:[],outL:[]})),Lk=o.links.map((l,k)=>({...l,k}));
  Lk.forEach(l=>{N[l.s].outL.push(l);N[l.t].inL.push(l);});
  N.forEach(n=>{n.v=Math.max(sumA(n.inL.map(l=>l.v)),sumA(n.outL.map(l=>l.v)));});
  const ncol=Math.max(...N.map(n=>n.col))+1,nw=W>=560?14:9,pad=W>=560?16:9,top=6,B=H-6,L=1;
  const lastW=Math.min(W*.3,Math.max(...N.filter(n=>n.col===ncol-1).map(n=>Math.max(TW(n.n,fs),TW(fmt(n.v,o.u),fs))))+10),R=W-lastW;
  const cols=[...Array(ncol)].map((_,c)=>N.filter(n=>n.col===c));
  const ky=Math.min(...cols.map(cn=>(B-top-(cn.length-1)*pad)/sumA(cn.map(n=>n.v))));
  cols.forEach((cn,c)=>{const tot=sumA(cn.map(n=>n.v))*ky+(cn.length-1)*pad;let y=top+(B-top-tot)/2;cn.forEach(n=>{n.x=L+c*(R-L-nw)/(ncol-1);n.y0=y;n.y1=y+n.v*ky;y=n.y1+pad;});});
  N.forEach(n=>{n.outL.sort((a,b)=>N[a.t].y0-N[b.t].y0);n.inL.sort((a,b)=>N[a.s].y0-N[b.s].y0);let y=n.y0;n.outL.forEach(l=>{l.sy=y;y+=l.v*ky;});y=n.y0;n.inL.forEach(l=>{l.ty=y;y+=l.v*ky;});});
  let lk='',nd='',lab='',defs='';
  Lk.forEach(l=>{const a=N[l.s],b=N[l.t],w=Math.max(.6,l.v*ky),x0=a.x+nw,x1=b.x,xm=(x0+x1)/2;
    const d=`M${n1(x0)},${n1(l.sy)}C${n1(xm)},${n1(l.sy)} ${n1(xm)},${n1(l.ty)} ${n1(x1)},${n1(l.ty)}V${n1(l.ty+w)}C${n1(xm)},${n1(l.ty+w)} ${n1(xm)},${n1(l.sy+w)} ${n1(x0)},${n1(l.sy+w)}Z`;
    const lc=l.c!=null?l.c:(o.linkBy==='target'?b.c:a.c);let fill=col(lc);
    if(o.grad){const id='skg'+(++UID);defs+=`<linearGradient id="${id}" gradientUnits="userSpaceOnUse" x1="${n1(x0)}" x2="${n1(x1)}" y1="0" y2="0"><stop offset="0" style="stop-color:${col(a.c)}"/><stop offset="1" style="stop-color:${col(b.c)}"/></linearGradient>`;fill=`url(#${id})`;}
    lk+=`<path class="lk${o.grad?' lkg':''}" data-i="${l.s}" data-j="${l.t}" d="${d}" style="fill:${fill}" data-t="${tipA(a.n+' → '+b.n,[[fmt(l.v,o.u),o.vn||'Value',lc],[(l.v/a.v*100).toFixed(0)+'%','of '+a.n,'muted']])}"/>`;});
  N.forEach(n=>{const h=Math.max(1.5,n.y1-n.y0);const tt=` data-t="${tipA(n.n,[[fmt(n.v,o.u),o.vn||'Value',n.c]].concat(n.inL.length&&n.outL.length?[[fmt(sumA(n.outL.map(l=>l.v)),o.u),'flows on','muted']]:[]))}"`;
    nd+=E.look==='3d'?prism(n.x,n.y0,nw,h,n.c,'m nd pr',n.i,'',true,5,tt):`<path class="m nd${kc(n.c)}" data-i="${n.i}" d="${bp(n.x,n.y0,nw,h,2,'all')}" style="fill:${col(n.c)}"${tt}/>`;
    const lx=n.x+nw+(E.look==='3d'?9:5),cy=(n.y0+n.y1)/2,an='start';
    const lf=W>=560?fs:fs-1,room=n.col<ncol-1?(R-L)/(ncol-1)-nw-4:lastW-6;
    if(h>=lf*2.1)lab+=`<text x="${n1(lx)}" y="${n1(cy-1)}" text-anchor="${an}" class="lb" font-size="${lf}">${esc(trunc(n.n,room,lf))}</text><text x="${n1(lx)}" y="${n1(cy+lf)}" text-anchor="${an}" class="lb lbv" font-size="${lf}">${fmt(n.v,o.u)}</text>`;
    else lab+=`<text x="${n1(lx)}" y="${n1(cy+lf*.36)}" text-anchor="${an}" class="lb" font-size="${lf}">${esc(trunc(n.n,room-TW(' 0000',lf),lf))} <tspan class="lbv">${fmt(n.v,o.u)}</tspan></text>`;});
  return svgWrap(W,H,fs,(defs?`<defs>${defs}</defs>`:'')+`<g class="lks">${lk}</g><g class="gm">${nd}</g>`+lab);
}};

/* ======================= Chord ======================= */
E.chord={draw(o,st,W,H){
  const fs=FS(W),n=o.names.length,M=o.m,rs=M.map(r=>sumA(r)),tot=sumA(rs),pad=.045;
  const lw=Math.max(...o.names.map(s=>TW(s,fs)));const ro=Math.max(30,Math.min(H/2-fs-6,W/2-lw-16)),ri=ro-(W>=560?13:9),cx=W/2,cy=H/2;
  const k=(Math.PI*2-pad*n)/tot;let a=-Math.PI/2+pad/2;const G=[];
  for(let i=0;i<n;i++){const g={i,a0:a,a1:a+rs[i]*k,sub:[]};let b=a;for(let j=0;j<n;j++){g.sub[j]={a0:b,a1:b+M[i][j]*k};b+=M[i][j]*k;}G.push(g);a=g.a1+pad;}
  const P=(r,t)=>n1(cx+r*Math.cos(t))+','+n1(cy+r*Math.sin(t));
  const lg=(t0,t1)=>t1-t0>Math.PI?1:0;
  let rb='',gs='',lab='';
  for(let i=0;i<n;i++)for(let j=i+1;j<n;j++){
    if(!M[i][j]&&!M[j][i])continue;const s=G[i].sub[j],t=G[j].sub[i];const dom=M[i][j]>=M[j][i]?i:j;const c=o.c?o.c[dom]:dom+1;
    const d=`M${P(ri,s.a0)}A${n1(ri)},${n1(ri)} 0 ${lg(s.a0,s.a1)},1 ${P(ri,s.a1)}Q${n1(cx)},${n1(cy)} ${P(ri,t.a0)}A${n1(ri)},${n1(ri)} 0 ${lg(t.a0,t.a1)},1 ${P(ri,t.a1)}Q${n1(cx)},${n1(cy)} ${P(ri,s.a0)}Z`;
    rb+=`<path class="rb2" data-i="${i}" data-j="${j}" d="${d}" style="fill:${col(c)}" data-t="${tipA(o.names[i]+' ⇄ '+o.names[j],[[fmt(M[i][j],o.u),o.names[i]+' → '+o.names[j],o.c?o.c[i]:i+1],[fmt(M[j][i],o.u),o.names[j]+' → '+o.names[i],o.c?o.c[j]:j+1]])}"/>`;}
  G.forEach(g=>{const c=o.c?o.c[g.i]:g.i+1;
    const d=`M${P(ro,g.a0)}A${n1(ro)},${n1(ro)} 0 ${lg(g.a0,g.a1)},1 ${P(ro,g.a1)}L${P(ri+1,g.a1)}A${n1(ri+1)},${n1(ri+1)} 0 ${lg(g.a0,g.a1)},0 ${P(ri+1,g.a0)}Z`;
    const inn=sumA(M.map(r=>r[g.i]));
    gs+=`<path class="chg${kc(c)}" data-i="${g.i}" d="${d}" style="fill:${col(c)}" data-t="${tipA(o.names[g.i],[[fmt(rs[g.i],o.u),o.outL||'Outgoing',c],[fmt(inn,o.u),o.inL||'Incoming','muted'],[fmtS(inn-rs[g.i],o.u),'Net','muted']])}"/>`;
    const m=(g.a0+g.a1)/2,cs=Math.cos(m),sn=Math.sin(m),lx=cx+(ro+6)*cs,ly=cy+(ro+6)*sn;const an=Math.abs(cs)<.22?'middle':cs>0?'start':'end';
    lab+=`<text x="${n1(lx)}" y="${n1(ly+fs*.36+(an==='middle'?(sn>0?fs*.5:-fs*.3):0))}" text-anchor="${an}" class="lb">${esc(o.names[g.i])}</text>`;});
  return svgWrap(W,H,fs,`<g class="rbs">${rb}</g><g class="gm">${gs}</g>`+lab);
}};

/* ======================= Network ======================= */
E.net={draw(o,st,W,H){
  const fs=FS(W),G=o.g||NET,nn=G.nodes.length;const items=(o.groups||[]).map((n,i)=>({n,c:i+1,t:'dot'}));
  const lg=items.length?legendSvg(items,4,fs+2,W-8,fs):{s:'',h:0};
  const padX=W>=560?60:30,top=lg.h+(W>=560?14:10),B=H-(W>=560?16:10);
  const X=v=>padX+v*(W-padX*2),Y=v=>top+v*(B-top);
  const vmax=Math.max(...G.nodes.map(d=>d.v)),rmin=W>=560?5:3.4,rmax=W>=560?15:9.5,wmax=Math.max(...G.links.map(l=>l.w));
  const nb=G.nodes.map(()=>new Set());G.links.forEach(l=>{nb[l.s].add(l.t);nb[l.t].add(l.s);});
  const rOf=d=>o.size==='deg'?rmin+Math.sqrt(d.deg/Math.max(...G.nodes.map(q=>q.deg)))*(rmax-rmin):rmin+Math.sqrt(d.v/vmax)*(rmax-rmin);
  let ls='',ns='',lab='';
  G.links.forEach(l=>{const a=G.nodes[l.s],b=G.nodes[l.t];ls+=`<line class="lk2${a.g===b.g?' same':''}" data-i="${l.s}" data-j="${l.t}" x1="${n1(X(a.x))}" y1="${n1(Y(a.y))}" x2="${n1(X(b.x))}" y2="${n1(Y(b.y))}" stroke-width="${n1(.7+l.w/wmax*(W>=560?3.4:2.2))}" data-t="${tipA(a.n+' + '+b.n,[[fmt(l.w),'Orders together',a.g+1]])}"/>`;});
  const order=[...Array(nn).keys()].sort((p,q)=>G.nodes[q].v-G.nodes[p].v);
  order.slice().reverse().forEach(i=>{const d=G.nodes[i],r=rOf(d);ns+=`<circle class="nd2 dot${kc(d.g+1)}" data-i="${i}" data-n="${[...nb[i]].join(' ')}" cx="${n1(X(d.x))}" cy="${n1(Y(d.y))}" r="${n1(r)}" style="fill:${col(d.g+1)}" data-t="${tipA(d.n,[[fmt(d.v,'$'),'Sales',d.g+1],[d.deg+' products','Bought together with','muted']])}"/>`;});
  const nl=o.labels==='all'||W>=560?nn:(o.labels||6);const placed=[];
  order.slice(0,nl).forEach(i=>{const d=G.nodes[i],r=rOf(d),x=X(d.x),y=Y(d.y),t=d.n,w=TW(t,fs-0.5);const right=x<W*.6;const lx=right?x+r+3:x-r-3;const bx=right?lx:lx-w;
    const box=[bx,y-fs*.6,bx+w,y+fs*.5];if(placed.some(p=>!(box[2]<p[0]||box[0]>p[2]||box[3]<p[1]||box[1]>p[3])))return;if(bx<1||bx+w>W-1)return;placed.push(box);
    lab+=`<text x="${n1(lx)}" y="${n1(y+fs*.34)}" text-anchor="${right?'start':'end'}" class="lb" font-size="${fs-0.5}">${esc(t)}</text>`;});
  return svgWrap(W,H,fs,`<g class="lks">${ls}</g><g class="gm">${ns}</g>`+lab+lg.s);
}};

/* ======================= Org chart (expand a team) ======================= */
E.org={draw(o,st,W,H){
  const fs=FS(W),P=o.people,root=P[0],ex=P.map((p,i)=>({...p,i})).filter(p=>p.p===0),open=st.open==null?null:+st.open;
  const team=open!=null?P.map((p,i)=>({...p,i})).filter(p=>p.p===open):[];
  const gap=W>=560?14:6,pad=W>=560?16:4,big=W>=560;
  const cw=Math.min(big?200:96,(W-pad*2-gap*(ex.length-1))/ex.length),ch=big?54:48;
  const rows=open!=null?3:2,y0=big?10:6,vgap=(H-y0*2-ch*rows)/(rows-1+.0001);
  const yy=r=>y0+r*(ch+Math.min(vgap,big?58:34));
  let s='',ln='';
  const card=(p,x,y,w,lvl,acts)=>{const c=p.c||'c1',r=big?14:10,initials=xInit(p.n);
    const teamN=P.filter(q=>q.p===p.i).length;
    let g=`<g class="oc${lvl===1?' oc1':''}${acts&&open===p.i?' open':''}" data-i="${p.i}"${acts?` data-act="open:${p.i}" role="button" aria-expanded="${open===p.i}"`:''} data-t="${tipA(p.n,[[p.t,'Role',c]].concat(p.hc?[[p.hc+' people','Team','muted']]:[]))}">`;
    g+=`<rect class="ocb" x="${n1(x)}" y="${n1(y)}" width="${n1(w)}" height="${ch}" rx="${big?10:7}"/><rect class="ocs${kc(c)}" x="${n1(x)}" y="${n1(y)}" width="${n1(w)}" height="${big?4:3}" rx="1.5" style="fill:${col(c)}"/>`;
    const vert=!big&&lvl>0;const ax=vert?x+w/2:x+(big?10:6)+r,ay=vert?y+13:y+ch/2+1,rr=vert?8.5:r;
    g+=`<circle class="av sph${kc(c)}" cx="${n1(ax)}" cy="${n1(ay)}" r="${rr}" style="fill:${col(c)}"/><text x="${n1(ax)}" y="${n1(ay+(fs-2)*.36)}" text-anchor="middle" class="li${ki(c)}" font-size="${fs-2}">${initials}</text>`;
    if(vert){g+=`<text x="${n1(ax)}" y="${n1(y+33)}" text-anchor="middle" class="oct" font-size="${fs-.5}">${esc(trunc(p.n,w-6,fs-.5))}</text><text x="${n1(ax)}" y="${n1(y+43)}" text-anchor="middle" class="ocs2" font-size="${fs-1.5}">${esc(trunc(p.ts||p.t,w-6,fs-1.5))}</text>`;}
    else{const tx=ax+r+(big?8:4),tw=x+w-tx-4-(lvl===1?16:0),sf=big?fs-1.5:fs-1;g+=`<text x="${n1(tx)}" y="${n1(ay-(big?3:1.5))}" class="oct">${esc(trunc(p.n,tw,fs))}</text><text x="${n1(tx)}" y="${n1(ay+fs-(big?0:1))}" class="ocs2" font-size="${sf}">${esc(trunc(big?p.t:(p.ts||p.t),tw,sf))}</text>`;}
    if(acts&&teamN)g+=`<g class="obadge"><circle cx="${n1(x+w-(big?12:9))}" cy="${n1(y+(big?13:10))}" r="${big?8:6.5}"/><text x="${n1(x+w-(big?12:9))}" y="${n1(y+(big?13:10)+(fs-2)*.36)}" text-anchor="middle" font-size="${fs-2}">${open===p.i?'−':teamN}</text></g>`;
    return g+'</g>';};
  /* root */
  const rw=Math.min(big?230:150,W-pad*2),rx=(W-rw)/2,ry=yy(0);const chS=ch;s+=card({...root,i:0},rx,ry,rw,0,false);
  const y1=yy(1),xs=ex.map((p,k)=>pad+k*(cw+gap)+(W-pad*2-(cw*ex.length+gap*(ex.length-1)))/2);
  const mid=ry+ch+(y1-ry-ch)/2;
  ln+=`<path class="ocl" d="M${n1(W/2)},${n1(ry+ch)}V${n1(mid)}M${n1(xs[0]+cw/2)},${n1(mid)}H${n1(xs[xs.length-1]+cw/2)}${xs.map(x=>`M${n1(x+cw/2)},${n1(mid)}V${n1(y1)}`).join('')}"/>`;
  ex.forEach((p,k)=>{s+=card(p,xs[k],y1,cw,1,true);});
  if(open!=null&&team.length){const y2=yy(2),k=ex.findIndex(p=>p.i===open),px=xs[k]+cw/2;const tw=Math.min(big?200:96,(W-pad*2-gap*(team.length-1))/team.length);
    let x0=px-(tw*team.length+gap*(team.length-1))/2;x0=Math.max(pad,Math.min(W-pad-(tw*team.length+gap*(team.length-1)),x0));
    const m2=y1+ch+(y2-y1-ch)/2;const tx=team.map((_,j)=>x0+j*(tw+gap)+tw/2);
    ln+=`<path class="ocl" d="M${n1(px)},${n1(y1+ch)}V${n1(m2)}M${n1(Math.min(px,tx[0]))},${n1(m2)}H${n1(Math.max(px,tx[tx.length-1]))}${tx.map(x=>`M${n1(x)},${n1(m2)}V${n1(y2)}`).join('')}"/>`;
    team.forEach((p,j)=>{s+=card({...p,c:ex[k].c},x0+j*(tw+gap),y2,tw,2,false);});}
  else if(open==null)s+=`<text x="${n1(W/2)}" y="${n1(H-6)}" text-anchor="middle" class="hintt">Click a leader to show the team</text>`;
  return svgWrap(W,H,fs,`<g class="ocls">${ln}</g><g class="gm">${s}</g>`);
},act(o,st,verb,arg){if(verb==='open'){st.open=st.open==null||+st.open!==+arg?+arg:null;return 'drill';}}};

/* ======================= Hierarchy tree (collapsible) ======================= */
E.htree={draw(o,st,W,H){
  const fs=FS(W),Hh=o.tree,col0=new Set((st.col||[]).map(Number));const cats=Hh.root.c.map((c,i)=>({n:c.n,i,v:agg(c)[0],kids:c.c.map(s=>({n:s.n,v:agg(s)[0]}))}));
  const tot=sumA(cats.map(c=>c.v));const rows=[];cats.forEach(c=>{if(col0.has(c.i))rows.push({cat:c,leaf:null});else c.kids.forEach(k=>rows.push({cat:c,leaf:k}));});
  const big=W>=560,top=big?10:6,B=H-(big?10:6),rh=(B-top)/rows.length;rows.forEach((r,k)=>{r.y=top+rh*(k+.5);});
  cats.forEach(c=>{const rr=rows.filter(r=>r.cat===c);c.y=(rr[0].y+rr[rr.length-1].y)/2;});
  const ry=(cats[0].y+cats[cats.length-1].y)/2;
  const x0=big?18:8,x1=W*(big?.26:.27),x2=W*(big?.5:.5),lw2=TW('Drivetrain',fs-1)+4,vw=TW('$1.6M',fs-1)+8,bw=W-x2-lw2-vw-4;
  const vmax=Math.max(...cats.flatMap(c=>c.kids.map(k=>k.v)));
  let ln='',s='',lab='';const curveH=(ax,ay,bx,by)=>{const m=(ax+bx)/2;return `M${n1(ax)},${n1(ay)}C${n1(m)},${n1(ay)} ${n1(m)},${n1(by)} ${n1(bx)},${n1(by)}`;};
  cats.forEach(c=>{ln+=`<path class="tl" d="${curveH(x0,ry,x1,c.y)}"/>`;});
  s+=`<circle class="tn0" cx="${x0}" cy="${n1(ry)}" r="${big?6:4.5}"/>`;
  lab+=`<text x="${x0-2}" y="${n1(ry-(big?12:9))}" class="lb">All</text><text x="${x0-2}" y="${n1(ry+(big?20:15))}" class="lb lbv">${fmt(tot,'$')}</text>`;
  rows.forEach(r=>{if(r.leaf){ln+=`<path class="tl${kc(r.cat.i+1)}" d="${curveH(x1,r.cat.y,x2-4,r.y)}" style="stroke:${col(r.cat.i+1)}"/>`;
    const w=Math.max(1,r.leaf.v/vmax*bw),bh=Math.min(rh*.62,big?16:10);
    s+=`<path class="m mh tb2${kc(r.cat.i+1)}" data-i="${r.cat.i}" d="${bp(x2+lw2,r.y-bh/2,w,bh,2,'r')}" style="fill:${col(r.cat.i+1)}" data-t="${tipA(r.cat.n+' › '+r.leaf.n,[[fmt(r.leaf.v,'$'),'Sales',r.cat.i+1],[(r.leaf.v/r.cat.v*100).toFixed(0)+'%','of '+r.cat.n,'muted']])}"/>`;
    lab+=`<text x="${n1(x2)}" y="${n1(r.y+(fs-1)*.36)}" class="tkn" font-size="${fs-1}">${esc(r.leaf.n)}</text>`;
    if(rh>=fs)lab+=`<text x="${n1(x2+lw2+4+w)}" y="${n1(r.y+(fs-1)*.36)}" class="tk" font-size="${fs-1}">${fmt(r.leaf.v,'$')}</text>`;}});
  cats.forEach(c=>{const closed=col0.has(c.i),r=big?8:6.5;
    s+=`<g class="tn" data-act="tog:${c.i}" role="button" aria-expanded="${!closed}" data-t="${tipA(c.n,[[fmt(c.v,'$'),'Sales',c.i+1],[closed?'Click to expand':'Click to collapse','','muted']])}"><circle class="sph${kc(c.i+1)}" cx="${n1(x1)}" cy="${n1(c.y)}" r="${r}" style="fill:${col(c.i+1)}"/><path class="tpm" d="M${n1(x1-r*.45)},${n1(c.y)}h${n1(r*.9)}${closed?`M${n1(x1)},${n1(c.y-r*.45)}v${n1(r*.9)}`:''}"/></g>`;
    if(closed)lab+=`<text x="${n1(x1+r+5)}" y="${n1(c.y+fs*.36)}" class="lb">${esc(c.n)} <tspan class="tk">${c.kids.length} subcategories · ${fmt(c.v,'$')}</tspan></text>`;
    else lab+=`<text x="${n1(x1)}" y="${n1(c.y-r-4)}" text-anchor="middle" class="lb">${esc(c.n)}</text>`;});
  return svgWrap(W,H,fs,`<g class="tls">${ln}</g><g class="gm">${s}</g>`+lab);
},act(o,st,verb,arg){if(verb==='tog'){const s=new Set((st.col||[]).map(Number));const k=+arg;s.has(k)?s.delete(k):s.add(k);st.col=[...s];return 'drill';}}};

/* ======================= Histogram ======================= */
E.hist={draw(o,st,W,H){
  const fs=FS(W),groups=o.groups,all=groups.flatMap(g=>g.v),nb=+(o.bins||16),bwSel=+(st.bw||o.bw||0);
  let T=ticks(Math.min(...all),Math.max(...all),nb),step=T.t[1]-T.t[0];if(bwSel){step=bwSel;T={lo:Math.floor(Math.min(...all)/step)*step,hi:Math.ceil((Math.max(...all)+1e-9)/step)*step};}
  const b0=T.lo,nbin=Math.max(1,Math.round((T.hi-T.lo)/step));
  const counts=groups.map(g=>{const c=Array(nbin).fill(0);g.v.forEach(x=>{let k=Math.floor((x-b0)/step);k=Math.max(0,Math.min(nbin-1,k));c[k]++;});return c;});
  const S=xStats(all);const pdf=x=>Math.exp(-.5*((x-S.mean)/S.sd)**2)/(S.sd*2.5066);
  let ymax=Math.max(...counts.flat());if(o.norm)ymax=Math.max(ymax,all.length*step*pdf(S.mean));
  const items=groups.length>1?groups.map((g,i)=>({n:g.n,c:g.c||i+1})):[];
  let ctl={s:'',w:0};if(o.binCtl){ctl=xBtns([50,100,250].map(b=>({k:'bw:'+b,t:'$'+b+' bins'})),'bw:'+(bwSel||100),0,0,fs-1);}
  const lg=legendSvg(items,4,fs+2,W-8-ctl.w,fs);const top=Math.max(lg.h,o.binCtl?fs+14:0)+(fs+4);
  const lw=xYw(0,ymax*1.04,'',fs,5),L=lw,R=W-(W>=560?14:8),B=H-fs-10;const ax=xYax(0,ymax*1.04,L,R,top,B,fs,'',5);const y=ax.y;
  const x=v=>L+(v-b0)/(T.hi-b0)*(R-L);let mk='',lab='',hov='';
  const ov=groups.length>1;const D3=E.look==='3d'&&!ov;
  counts.forEach((cs,gi)=>{const c=groups[gi].c||gi+1;cs.forEach((n,k)=>{if(!n)return;const xa=x(b0+k*step)+.8,xb=x(b0+(k+1)*step)-.8,ya=y(n);const dl=`animation-delay:${k*22}ms`+(ov?';fill-opacity:.62':'');
    mk+=D3?prism(xa,ya,xb-xa,B-ya,c,'m pr',gi,dl,true,6):`<path class="m${kc(c)}${ov?' ovl':''}" data-i="${gi}" d="${bp(xa,ya,xb-xa,B-ya,ov?1:2,'t')}" style="fill:${col(c)};${dl}"/>`;});});
  for(let k=0;k<nbin;k++){const a=b0+k*step,b=a+step;hov+=`<rect class="hit" x="${n1(x(a))}" y="${n1(top)}" width="${n1(x(b)-x(a))}" height="${n1(B-top)}" data-t="${tipA(fmt(a,o.u)+' – '+fmt(b,o.u),groups.map((g,gi)=>[String(counts[gi][k]),g.n,g.c||gi+1]))}"/>`;}
  const XT=ticks(b0,T.hi,W>=560?8:5);XT.t.filter(t=>t>=b0-1e-9&&t<=T.hi+1e-9).forEach(t=>{lab+=`<text x="${n1(x(t))}" y="${n1(B+fs+4)}" text-anchor="middle" class="tk">${fmt(t,o.u)}</text>`;});
  if(o.norm){const pts=[];for(let k=0;k<=60;k++){const v=b0+(T.hi-b0)*k/60;pts.push([x(v),y(all.length*step*pdf(v))]);}lab+=`<path class="nc" d="${monoPath(pts)}"/>`;}
  if(o.stats){[[S.mean,'Mean',''],[S.md,'Median','md']].forEach(([v,n,c],k)=>{const xx=n1(x(v));lab+=`<line class="ref" x1="${xx}" x2="${xx}" y1="${n1(top-2)}" y2="${n1(B)}"/><text x="${n1(x(v)+(k?-4:4))}" y="${n1(top+fs-2)}" text-anchor="${k?'end':'start'}" class="reft">${n} ${fmt(v,o.u)}</text>`;});}
  return svgWrap(W,H,fs,ax.g+`<line class="bl" x1="${n1(L)}" x2="${n1(R)}" y1="${n1(B+.5)}" y2="${n1(B+.5)}"/><g class="gm">${mk}</g>`+lab+hov+lg.s+(ctl.s?`<g transform="translate(${n1(W-ctl.w-4)},2)">${ctl.s}</g>`:''));
},act(o,st,verb,arg){if(verb==='bw'){st.bw=+arg;return true;}}};

/* ======================= Box and whisker ======================= */
E.box={draw(o,st,W,H){
  const fs=FS(W);let gs=o.groups.map((g,i)=>({...g,i,S:xStats(g.v),c:g.c||i+1}));if(o.sort)gs.sort((a,b)=>a.S.md-b.S.md);
  const V=(o.dir||'v')==='v',all=gs.flatMap(g=>g.v),lo=o.zero?0:Math.min(...all),hi=Math.max(...all),n=gs.length;
  let g='',mk='',lab='',pts='';const jit=rng(9);
  if(V){const lw=xYw(lo,hi,o.u,fs),L=lw,R=W-6,top=8,B=H-fs-10,ax=xYax(lo,hi,L,R,top,B,fs,o.u,5),y=ax.y,bw=(R-L)/n;g=ax.g;
    gs.forEach((d,k)=>{const cx=L+bw*(k+.5),w=Math.min(bw*(o.points==='side'?.3:.44),W>=560?60:34),S=d.S,c=d.c;const bx=o.points==='side'?cx-w*.85:cx-w/2;const mx=bx+w/2;
      const light=o.points==='jitter';const tt=` data-t="${tipA(d.n,[[fmt(S.md,o.u),'Median',c],[fmt(S.q1,o.u)+' – '+fmt(S.q3,o.u),'Middle 50%','muted'],[fmt(S.lo,o.u)+' – '+fmt(S.hi,o.u),'Whiskers','muted'],[String(S.out.length),'Outliers','muted']])}"`;
      mk+=`<g class="bxg" data-i="${d.i}"${tt}><path class="wh" d="M${n1(mx)},${n1(y(S.hi))}V${n1(y(S.q3))}M${n1(mx)},${n1(y(S.q1))}V${n1(y(S.lo))}M${n1(mx-w*.25)},${n1(y(S.hi))}h${n1(w*.5)}M${n1(mx-w*.25)},${n1(y(S.lo))}h${n1(w*.5)}"/>`;
      mk+=`<rect class="bx${light?' light':' gf'}${kc(c)}" x="${n1(bx)}" y="${n1(y(S.q3))}" width="${n1(w)}" height="${n1(Math.max(1,y(S.q1)-y(S.q3)))}" rx="3" style="fill:${col(c)};stroke:${col(c)}"/><line class="md${light?' dk':''}" x1="${n1(bx+1.5)}" x2="${n1(bx+w-1.5)}" y1="${n1(y(S.md))}" y2="${n1(y(S.md))}"/>`;
      if(o.mean)mk+=`<path class="mn" d="M${n1(mx)},${n1(y(S.mean)-4)}l4,4l-4,4l-4,-4Z"/>`;
      if(!o.points)S.out.forEach(v=>{mk+=`<circle class="ol" cx="${n1(mx)}" cy="${n1(y(v))}" r="2.6" style="stroke:${col(c)}"/>`;});mk+='</g>';
      if(o.points==='jitter'||o.points==='side'){const sx=o.points==='side'?cx+w*.45:cx,sw=o.points==='side'?w*.9:w*.7;d.v.forEach(v=>{pts+=`<circle class="jt${kc(c)}" data-i="${d.i}" cx="${n1(sx-sw/2+jit()*sw)}" cy="${n1(y(v))}" r="${W>=560?2.6:1.8}" style="fill:${col(c)}"/>`;});}
      lab+=`<text x="${n1(cx)}" y="${n1(B+fs+4)}" text-anchor="middle" class="tk">${esc(trunc(d.n,bw-4,fs))}</text>`;});
    if(o.yt)lab+=`<text x="${n1(L)}" y="${fs}" class="axt">${esc(o.yt)}</text>`;
  }else{const lw=Math.max(...gs.map(d=>TW(d.n,fs)))+10,L=lw,R=W-xRp(lo,hi,o.u,fs,5),top=4,B=H-fs-10,ax=xXax(lo,hi,L,R,top,B,fs,o.u,5),x=ax.x,bh=(B-top)/n;g=ax.g;
    gs.forEach((d,k)=>{const cy=top+bh*(k+.5),h=Math.min(bh*.5,W>=560?30:16),S=d.S,c=d.c;const tt=` data-t="${tipA(d.n,[[fmt(S.md,o.u),'Median',c],[fmt(S.q1,o.u)+' – '+fmt(S.q3,o.u),'Middle 50%','muted'],[fmt(S.lo,o.u)+' – '+fmt(S.hi,o.u),'Whiskers','muted']])}"`;
      mk+=`<g class="bxg" data-i="${d.i}"${tt}><path class="wh" d="M${n1(x(S.lo))},${n1(cy)}H${n1(x(S.q1))}M${n1(x(S.q3))},${n1(cy)}H${n1(x(S.hi))}M${n1(x(S.lo))},${n1(cy-h*.25)}v${n1(h*.5)}M${n1(x(S.hi))},${n1(cy-h*.25)}v${n1(h*.5)}"/>`;
      mk+=`<rect class="bx gf${kc(c)}" x="${n1(x(S.q1))}" y="${n1(cy-h/2)}" width="${n1(Math.max(1,x(S.q3)-x(S.q1)))}" height="${n1(h)}" rx="3" style="fill:${col(c)};stroke:${col(c)}"/><line class="md" x1="${n1(x(S.md))}" x2="${n1(x(S.md))}" y1="${n1(cy-h/2+1.5)}" y2="${n1(cy+h/2-1.5)}"/>`;
      S.out.forEach(v=>{mk+=`<circle class="ol" cx="${n1(x(v))}" cy="${n1(cy)}" r="2.6" style="stroke:${col(c)}"/>`;});mk+='</g>';
      lab+=`<text x="${n1(L-6)}" y="${n1(cy+fs*.36)}" text-anchor="end" class="tkn">${esc(d.n)}</text>`;});
}
  return svgWrap(W,H,fs,g+`<g class="gm">${mk}</g><g class="jts">${pts}</g>`+lab);
}};

/* ======================= Violin and raincloud ======================= */
E.violin={draw(o,st,W,H){
  const fs=FS(W),gs=o.groups.map((g,i)=>({...g,i,S:xStats(g.v),c:g.c||i+1})),n=gs.length,all=gs.flatMap(g=>g.v);
  const lo=o.zero?0:Math.min(...all),hi=Math.max(...all),lw=xYw(lo,hi,o.u,fs),L=lw,R=W-6,top=8,B=H-fs-10,ax=xYax(lo,hi,L,R,top,B,fs,o.u,5),y=ax.y,bw=(R-L)/n;
  const K=gs.map(d=>xKde(d.v,d.S.min,d.S.max,44));const dmax=Math.max(...K.flat().map(p=>p[1]));const jit=rng(5);
  let mk='',lab='',pts='';
  gs.forEach((d,k)=>{const cx=L+bw*(k+.5),half=bw*(o.rain?.46:.42),c=d.c,S=d.S,ws=v=>v/dmax*half;
    const side=o.rain?cx-bw*.06:cx;
    const right=K[k].map(p=>[side+ws(p[1]),y(p[0])]),left=K[k].map(p=>[side-ws(p[1]),y(p[0])]).reverse();
    const dd=o.rain?`M${n1(side)},${n1(y(S.min))}`+left.map(p=>`L${n1(p[0])},${n1(p[1])}`).join('')+`L${n1(side)},${n1(y(S.max))}Z`:'M'+right.map(p=>n1(p[0])+','+n1(p[1])).join('L')+'L'+left.map(p=>n1(p[0])+','+n1(p[1])).join('L')+'Z';
    mk+=`<path class="vio gf${kc(c)}${o.box||o.rain?' soft':''}" data-i="${d.i}" d="${dd}" style="fill:${col(c)}" data-t="${tipA(d.n,[[fmt(S.md,o.u),'Median',c],[fmt(S.mean,o.u),'Mean','muted'],[fmt(S.min,o.u)+' – '+fmt(S.max,o.u),'Range','muted'],[String(S.n),'Observations','muted']])}"/>`;
    if(o.box||o.rain){const bw2=Math.max(4,Math.min(10,bw*.08)),bx=o.rain?cx+bw*.02:cx-bw2/2;mk+=`<path class="vwh" d="M${n1(bx+bw2/2)},${n1(y(S.hi))}V${n1(y(S.lo))}"/><rect class="vbx" x="${n1(bx)}" y="${n1(y(S.q3))}" width="${n1(bw2)}" height="${n1(Math.max(1,y(S.q1)-y(S.q3)))}" rx="2"/><circle class="vmd" cx="${n1(bx+bw2/2)}" cy="${n1(y(S.md))}" r="${W>=560?3.2:2.3}"/>`;}
    if(o.rain){const x0=cx+bw*.1,ww=bw*.32;d.v.forEach(v=>{pts+=`<circle class="jt${kc(c)}" data-i="${d.i}" cx="${n1(x0+jit()*ww)}" cy="${n1(y(v))}" r="${W>=560?2.4:1.7}" style="fill:${col(c)}"/>`;});}
    lab+=`<text x="${n1(cx)}" y="${n1(B+fs+4)}" text-anchor="middle" class="tk">${esc(trunc(d.n,bw-4,fs))}</text>`;});
  if(o.yt)lab+=`<text x="${n1(L)}" y="${fs}" class="axt">${esc(o.yt)}</text>`;
  return svgWrap(W,H,fs,ax.g+`<g class="gm">${mk}</g><g class="jts">${pts}</g>`+lab);
}};

/* ======================= Bullet chart ======================= */
E.bullet={draw(o,st,W,H){
  const fs=FS(W),it=o.items,n=it.length,V=o.dir==='v',big=W>=560;let s='',lab='';
  const stat=d=>{const r=d.inv?d.t/d.v:d.v/d.t;return r>=1?'good':r>=.95?'warn':'crit';};
  if(!V){const lw=Math.min(W*.32,Math.max(...it.map(d=>TW(d.n,fs)))+12),vw=Math.max(...it.map(d=>TW(fmt(d.v,d.u),fs)))+10,L=lw,R=W-vw-4,top=4,B=H-4,rh=(B-top)/n;
    it.forEach((d,k)=>{const y0=top+rh*k,bh=Math.min(rh*.66,big?34:22),cy=y0+rh/2,yb=cy-bh/2,x=v=>L+v/d.max*(R-L);const c=o.status?stat(d):1,ah=bh*.36;
      [[d.max,'bd3'],[d.b[1],'bd2'],[d.b[0],'bd1']].forEach(([v,cl])=>{s+=`<rect class="${cl}" x="${n1(L)}" y="${n1(yb)}" width="${n1(x(v)-L)}" height="${n1(bh)}" rx="2"/>`;});
      const tt=` data-t="${tipA(d.n,[[fmt(d.v,d.u),'Actual',c],[fmt(d.t,d.u),'Target','ink'],[((d.inv?d.t/d.v:d.v/d.t)*100).toFixed(0)+'%','of target','muted']])}"`;
      s+=E.look==='3d'?prism(L,cy-ah/2,x(d.v)-L,ah,c,'m mh pr',k,`animation-delay:${k*70}ms`,false,6,tt):`<path class="m mh${kc(c)}" data-i="${k}" d="${bp(L,cy-ah/2,x(d.v)-L,ah,2,'r')}" style="fill:${col(c)};animation-delay:${k*70}ms"${tt}/>`;
      s+=`<line class="bt" x1="${n1(x(d.t))}" x2="${n1(x(d.t))}" y1="${n1(cy-bh*.4)}" y2="${n1(cy+bh*.4)}"/>`;
      lab+=`<text x="${n1(L-8)}" y="${n1(cy-(rh>fs*2.6?2:-fs*.36))}" text-anchor="end" class="lbt" font-weight="600">${esc(d.n)}</text>`;if(rh>fs*2.6)lab+=`<text x="${n1(L-8)}" y="${n1(cy+fs)}" text-anchor="end" class="tk" font-size="${fs-1}">${esc(d.sub||'')}</text>`;
      lab+=`<text x="${n1(R+6)}" y="${n1(cy+fs*.36)}" class="tk2">${fmt(d.v,d.u)}</text>`;});
  }else{const top=fs+8,B=H-fs*2-10,cw=(W-8)/n;
    it.forEach((d,k)=>{const cx=4+cw*(k+.5),bw=Math.min(cw*.42,big?44:24),xb=cx-bw/2,y=v=>B-v/d.max*(B-top),c=o.status?stat(d):1,aw=bw*.36;
      [[d.max,'bd3'],[d.b[1],'bd2'],[d.b[0],'bd1']].forEach(([v,cl])=>{s+=`<rect class="${cl}" x="${n1(xb)}" y="${n1(y(v))}" width="${n1(bw)}" height="${n1(B-y(v))}" rx="2"/>`;});
      const tt=` data-t="${tipA(d.n,[[fmt(d.v,d.u),'Actual',c],[fmt(d.t,d.u),'Target','ink']])}"`;
      s+=E.look==='3d'?prism(cx-aw/2,y(d.v),aw,B-y(d.v),c,'m pr',k,`animation-delay:${k*70}ms`,true,6,tt):`<path class="m${kc(c)}" data-i="${k}" d="${bp(cx-aw/2,y(d.v),aw,B-y(d.v),2,'t')}" style="fill:${col(c)};animation-delay:${k*70}ms"${tt}/>`;
      s+=`<line class="bt" x1="${n1(cx-bw*.42)}" x2="${n1(cx+bw*.42)}" y1="${n1(y(d.t))}" y2="${n1(y(d.t))}"/>`;
      lab+=`<text x="${n1(cx)}" y="${n1(top-6)}" text-anchor="middle" class="tk2">${fmt(d.v,d.u)}</text>`;
      if(TW(d.n,fs)>cw-4&&d.n.includes(' ')){const w=d.n.split(' '),h=Math.ceil(w.length/2);lab+=`<text x="${n1(cx)}" y="${n1(B+fs+4)}" text-anchor="middle" class="lbt" font-weight="600">${esc(trunc(w.slice(0,h).join(' '),cw-2,fs))}</text><text x="${n1(cx)}" y="${n1(B+fs*2+6)}" text-anchor="middle" class="lbt" font-weight="600">${esc(trunc(w.slice(h).join(' '),cw-2,fs))}</text>`;}
      else lab+=`<text x="${n1(cx)}" y="${n1(B+fs+4)}" text-anchor="middle" class="lbt" font-weight="600">${esc(trunc(d.n,cw-4,fs))}</text><text x="${n1(cx)}" y="${n1(B+fs*2+6)}" text-anchor="middle" class="tk" font-size="${fs-1}">${esc(trunc(d.sub||'',cw-4,fs-1))}</text>`;});}
  return svgWrap(W,H,fs,`<g class="gm">${s}</g>`+lab);
}};

/* ======================= Parallel coordinates ======================= */
E.parcoord={draw(o,st,W,H){
  const fs=FS(W),D=o.dims,rows=o.rows,lgd=o.groups?legendSvg(o.groups.map((n,i)=>({n,c:i+1,t:'line'})),4,fs+1,W-8,fs):{s:'',h:0},t0=lgd.h,top=t0+fs*2+6,B=H-fs-8,L=W>=560?40:22,R=W-(W>=560?40:22),nx=D.length;
  const X=k=>L+k*(R-L)/(nx-1);const sc=D.map((d,k)=>{const vs=rows.map(r=>r.v[k]);const T=ticks(Math.min(...vs),Math.max(...vs),4);return {T,y:v=>B-(v-T.lo)/((T.hi-T.lo)||1)*(B-top)};});
  let ax='',ln='',lab='';
  D.forEach((d,k)=>{const x=X(k);ax+=`<line class="pca" x1="${n1(x)}" x2="${n1(x)}" y1="${n1(top)}" y2="${n1(B)}"/>`;lab+=`<text x="${n1(x)}" y="${n1(t0+fs+1)}" text-anchor="middle" class="lbt" font-weight="600">${esc(d.n)}</text>`;
    [sc[k].T.lo,sc[k].T.hi].forEach((t,j)=>{lab+=`<text x="${n1(x+(k===nx-1?-4:4))}" y="${n1(j?top-3:B+fs+2)}" text-anchor="${k===nx-1?'end':'start'}" class="tk" font-size="${fs-1}">${fmt(t,d.u)}</text>`;});});
  rows.forEach((r,i)=>{const pts=r.v.map((v,k)=>[X(k),sc[k].y(v)]);ln+=`<path class="pc${kc(r.g+1)}" data-i="${r.g}" d="${linePath(pts)}" style="stroke:${col(r.g+1)}" data-t="${tipA(r.n,D.map((d,k)=>[fmt(r.v[k],d.u),d.n,k?'muted':r.g+1]))}"/>`;});
  return svgWrap(W,H,fs,ax+`<g class="pcs">${ln}</g>`+lab+lgd.s);
}};

/* ======================= Lollipop ======================= */
E.lolli={draw(o,st,W,H){
  const fs=FS(W),V=o.dir==='v';let idx=[...o.v.keys()];if(o.sort)idx.sort((a,b)=>o.v[b]-o.v[a]);
  const vals=idx.map(i=>o.v[i]),cats=idx.map(i=>o.cats[i]),lo=Math.min(0,...vals),hi=Math.max(0,...vals),r=W>=560?7:4.6;
  let g='',s='',lab='';
  const ct=v=>o.div?(v>=0?'dpos':'dneg'):1;
  if(!V){const lw=Math.max(...cats.map(c=>TW(c,fs)))+10,vw=Math.max(TW(fmt(hi,o.u),fs)+12,xRp(lo,hi,o.u,fs,4)),L=lw,R=W-vw,top=4,B=H-fs-10,ax=xXax(lo,hi,L,R,top,B,fs,o.u,4),x=ax.x,bh=(B-top)/cats.length;g=ax.g;
    cats.forEach((c,k)=>{const cy=top+bh*(k+.5),v=vals[k],t=ct(v);s+=`<g class="lp" data-i="${idx[k]}" data-t="${tipA(c,[[fmt(v,o.u),o.vn||'Value',t]])}"><line class="stem" x1="${n1(x(0))}" x2="${n1(x(v))}" y1="${n1(cy)}" y2="${n1(cy)}" style="stroke:${col(t)}"/><circle class="head dot${kc(t)}" cx="${n1(x(v))}" cy="${n1(cy)}" r="${r}" style="fill:${col(t)}"/></g>`;
      lab+=`<text x="${n1(L-6)}" y="${n1(cy+fs*.36)}" text-anchor="end" class="tkn">${esc(c)}</text>`;if(o.labels!==false)lab+=`<text x="${n1(x(v)+(v>=0?r+4:-r-4))}" y="${n1(cy+fs*.36)}" text-anchor="${v>=0?'start':'end'}" class="tk">${fmt(v,o.u)}</text>`;});
  }else{const lw=xYw(lo,hi,o.u,fs),L=lw,R=W-6,top=o.labels!==false?fs+6:8,B=H-fs-10,ax=xYax(lo,hi,L,R,top,B,fs,o.u,4),y=ax.y,bw=(R-L)/cats.length;g=ax.g;
    cats.forEach((c,k)=>{const cx=L+bw*(k+.5),v=vals[k],t=ct(v);s+=`<g class="lp" data-i="${idx[k]}" data-t="${tipA(c,[[o.div?fmtS(v,o.u):fmt(v,o.u),o.vn||'Value',t]])}"><line class="stem" x1="${n1(cx)}" x2="${n1(cx)}" y1="${n1(y(0))}" y2="${n1(y(v))}" style="stroke:${col(t)}"/><circle class="head dot${kc(t)}" cx="${n1(cx)}" cy="${n1(y(v))}" r="${r}" style="fill:${col(t)}"/></g>`;
      lab+=`<text x="${n1(cx)}" y="${n1(B+fs+4)}" text-anchor="middle" class="tk">${esc(trunc(c,bw,fs))}</text>`;if(o.labels!==false&&(W>=560||k%2===0||o.div))lab+=`<text x="${n1(cx)}" y="${n1(y(v)+(v>=0?-r-4:r+fs))}" text-anchor="middle" class="tk" font-size="${fs-1}">${o.div?fmtS(v,o.u):fmt(v,o.u)}</text>`;});}
  return svgWrap(W,H,fs,g+`<g class="gm">${s}</g>`+lab);
}};

/* ======================= Dumbbell ======================= */
E.dumbbell={draw(o,st,W,H){
  const fs=FS(W),rows=o.rows.slice();if(o.sort==='delta')rows.sort((a,b)=>(b.b-b.a)-(a.b-a.a));else if(o.sort)rows.sort((a,b)=>b.b-a.b);
  const range=o.range;const vals=rows.flatMap(r=>range?[r.lo,r.hi]:[r.a,r.b]);const lo=o.zero===false?Math.min(...vals):0,hi=Math.max(...vals);
  const items=range?[{n:'Lowest to highest',c:'ink2',t:'line'},{n:'Average',c:1,t:'dot'}]:[{n:o.an,c:2,t:'dot'},{n:o.bn,c:1,t:'dot'}];
  const lg=legendSvg(items,4,fs+1,W-8,fs);const lw=Math.max(...rows.map(r=>TW(r.n,fs)))+10,L=lw,R=W-Math.max(xRp(lo,hi,o.u,fs,4),range?10:TW('+10.0%',fs-1)+12),top=lg.h+4,B=H-fs-10,ax=xXax(lo,hi,L,R,top,B,fs,o.u,4),x=ax.x,bh=(B-top)/rows.length,r=W>=560?6.5:4.4;
  let s='',lab='';
  rows.forEach((d,k)=>{const cy=top+bh*(k+.5);
    if(range){s+=`<g data-i="${k}" data-t="${tipA(d.n,[[fmt(d.lo,o.u),'Lowest','ink2'],[fmt(d.mid,o.u),'Average',1],[fmt(d.hi,o.u),'Highest','ink2']])}"><line class="db rng" x1="${n1(x(d.lo))}" x2="${n1(x(d.hi))}" y1="${n1(cy)}" y2="${n1(cy)}"/><circle class="rend" cx="${n1(x(d.lo))}" cy="${n1(cy)}" r="${n1(r*.62)}"/><circle class="rend" cx="${n1(x(d.hi))}" cy="${n1(cy)}" r="${n1(r*.62)}"/><circle class="dot${kc(1)}" cx="${n1(x(d.mid))}" cy="${n1(cy)}" r="${r}" style="fill:var(--c1)"/></g>`;}
    else{const up=d.b>=d.a;s+=`<g data-i="${k}" data-t="${tipA(d.n,[[fmt(d.b,o.u),o.bn,1],[fmt(d.a,o.u),o.an,2],[fmtS((d.b/d.a-1)*100,'%'),'Change',up?'good':'crit']])}"><line class="db${up?' up':' dn'}" x1="${n1(x(d.a))}" x2="${n1(x(d.b))}" y1="${n1(cy)}" y2="${n1(cy)}"/><circle class="dot${kc(2)}" cx="${n1(x(d.a))}" cy="${n1(cy)}" r="${r}" style="fill:var(--c2)"/><circle class="dot${kc(1)}" cx="${n1(x(d.b))}" cy="${n1(cy)}" r="${r}" style="fill:var(--c1)"/></g>`;
      if(o.labels!==false){const ch=(d.b/d.a-1)*100;lab+=`<text x="${n1(Math.max(x(d.a),x(d.b))+r+4)}" y="${n1(cy+(fs-1)*.36)}" class="tk${ch>=0?' tup':' tdn'}" font-size="${fs-1}">${fmtS(ch,'%')}</text>`;}}
    lab+=`<text x="${n1(L-6)}" y="${n1(cy+fs*.36)}" text-anchor="end" class="tkn">${esc(d.n)}</text>`;});
  return svgWrap(W,H,fs,ax.g+`<g class="gm">${s}</g>`+lab+lg.s);
}};

/* ======================= Slope chart ======================= */
E.slope={draw(o,st,W,H){
  const fs=FS(W),rows=o.rows,vals=rows.flatMap(r=>[r.a,r.b]),lo=Math.min(...vals),hi=Math.max(...vals),pad=(hi-lo)*.06,hl=o.hl;
  const lt=r=>`${r.n} ${fmt(r.a,o.u)}`,rt=(r,i)=>hl===i||(hl==null&&W>=560)?`${fmt(r.b,o.u)} ${r.n}`:fmt(r.b,o.u);
  const L=Math.min(W*.5,Math.max(...rows.map(r=>TW(lt(r),fs)))+14),R=W-Math.min(W*.34,Math.max(...rows.map((r,i)=>TW(rt(r,i),fs)))+14),top=fs*2+6,B=H-8;
  const y=v=>B-(v-(lo-pad))/((hi-lo+pad*2)||1)*(B-top);let s='',ln='',lab='';
  lab+=`<text x="${n1(L)}" y="${fs+2}" text-anchor="middle" class="lbt" font-weight="650">${esc(o.an)}</text><text x="${n1(R)}" y="${fs+2}" text-anchor="middle" class="lbt" font-weight="650">${esc(o.bn)}</text>`;
  ln+=`<line class="pca" x1="${n1(L)}" x2="${n1(L)}" y1="${n1(top-4)}" y2="${n1(B)}"/><line class="pca" x1="${n1(R)}" x2="${n1(R)}" y1="${n1(top-4)}" y2="${n1(B)}"/>`;
  const LL=[],RR=[];const ord=rows.map((_,i)=>i).sort((a,b)=>(a===hl)-(b===hl));
  ord.forEach(i=>{const r=rows[i],c=hl!=null?(i===hl?1:'muted-mark'):(r.c||i+1),up=r.b>=r.a,w=hl!=null&&i!==hl?1.8:2.8;
    const tt=` data-t="${tipA(r.n,[[fmt(r.a,o.u),o.an,c],[fmt(r.b,o.u),o.bn,c],[o.u==='%'?fmtS(r.b-r.a,'pt'):fmtS((r.b/r.a-1)*100,'%'),'Change',up?'good':'crit']])}"`;
    ln+=`<line class="sl2${hl!=null&&i===hl?' hi':''}" data-i="${i}" x1="${n1(L)}" x2="${n1(R)}" y1="${n1(y(r.a))}" y2="${n1(y(r.b))}" stroke-width="${w}" style="stroke:${col(c)}"${tt}/>`;
    s+=`<g data-i="${i}"${tt}><circle class="dot${kc(c)}" cx="${n1(L)}" cy="${n1(y(r.a))}" r="${W>=560?5:3.8}" style="fill:${col(c)}"/><circle class="dot${kc(c)}" cx="${n1(R)}" cy="${n1(y(r.b))}" r="${W>=560?5:3.8}" style="fill:${col(c)}"/></g>`;
    LL.push({y:y(r.a)+fs*.36,t:lt(r),hi:hl===i,dim:hl!=null&&hl!==i});RR.push({y:y(r.b)+fs*.36,t:rt(r,i),hi:hl===i,dim:hl!=null&&hl!==i});});
  const cls=it=>it.hi?'lbt':it.dim?'tk':'tkn';
  xSpread(LL,fs+2,top,B+fs*.36).forEach(it=>{lab+=`<text x="${n1(L-8)}" y="${n1(it.y)}" text-anchor="end" class="${cls(it)}"${it.hi?' font-weight="650"':''}>${esc(it.t)}</text>`;});
  xSpread(RR,fs+2,top,B+fs*.36).forEach(it=>{lab+=`<text x="${n1(R+8)}" y="${n1(it.y)}" class="${cls(it)}"${it.hi?' font-weight="650"':''}>${esc(it.t)}</text>`;});
  return svgWrap(W,H,fs,`<g class="lns">${ln}</g><g class="gm">${s}</g>`+lab);
}};

/* ======================= Bump chart ======================= */
E.bump={draw(o,st,W,H){
  const fs=FS(W),P=o.periods,S=o.series,n=S.length,hl=o.hl;const nw=Math.max(...S.map(s=>TW(s.n,fs)))+16;
  const L=W>=560?46:32,R=W-nw-8,top=fs+12,B=H-fs-12,x=k=>L+k*(R-L)/(P.length-1),y=r=>top+(r-1)*(B-top)/(n-1),rr=W>=560?9:6.4;
  let s='',ln='',lab='';const every=(R-L)/(P.length-1)<TW(P[0],fs)+6?2:1;
  for(let r=1;r<=n;r++)lab+=`<text x="${n1(L-rr-6)}" y="${n1(y(r)+fs*.36)}" text-anchor="end" class="tk">#${r}</text>`;
  P.forEach((p,k)=>{if(k%every===0)lab+=`<text x="${n1(x(k))}" y="${n1(H-4)}" text-anchor="middle" class="tk">${esc(p)}</text>`;});
  const ord=S.map((_,i)=>i).sort((a,b)=>(a===hl)-(b===hl));
  ord.forEach(i=>{const sr=S[i],c=hl!=null?(i===hl?1:'muted-mark'):i+1,pts=sr.r.map((r,k)=>[x(k),y(r)]);
    ln+=`<path class="bl2" data-i="${i}" d="${monoPath(pts)}" style="stroke:${col(c)}" stroke-width="${hl!=null&&i!==hl?2:3.2}"/>`;
    s+=`<g data-i="${i}">`;pts.forEach((p,k)=>{s+=`<g data-t="${tipA(sr.n+' · '+P[k],[['#'+sr.r[k],'Rank',c]].concat(sr.v?[[fmt(sr.v[k],o.u),'Sales','muted']]:[]))}"><circle class="bpt sph${kc(c)}" cx="${n1(p[0])}" cy="${n1(p[1])}" r="${rr}" style="fill:${col(c)}"/><text x="${n1(p[0])}" y="${n1(p[1]+(fs-2)*.36)}" text-anchor="middle" class="li${ki(c)}" font-size="${fs-2}">${sr.r[k]}</text></g>`;});
    s+='</g>';lab+=`<text x="${n1(R+rr+6)}" y="${n1(y(sr.r[sr.r.length-1])+fs*.36)}" class="${hl!=null&&i!==hl?'tk':'lbt'}" font-weight="600">${esc(sr.n)}</text>`;});
  return svgWrap(W,H,fs,`<g class="lns">${ln}</g><g class="gm">${s}</g>`+lab);
}};

/* ======================= Tornado ======================= */
E.tornado={draw(o,st,W,H){
  const fs=FS(W),big=W>=560;let s='',lab='',g='';
  if(o.base==null){/* back-to-back bars */
    const cats=o.cats,n=cats.length,mx=Math.max(...o.l,...o.r),gw=Math.max(...cats.map(c=>TW(c,fs)))+14,cx=W/2,L=6,R=W-6,top=fs+12,B=H-fs-8,bh=(B-top)/n,hw=(cx-gw/2)-L-(big?44:30);
    const xl=v=>cx-gw/2-v/mx*hw,xr=v=>cx+gw/2+v/mx*hw;
    lab+=`<text x="${n1(cx-gw/2-4)}" y="${fs+2}" text-anchor="end" class="lbt" font-weight="650"><tspan style="fill:var(--c2)">●</tspan> ${esc(o.ln)}</text><text x="${n1(cx+gw/2+4)}" y="${fs+2}" class="lbt" font-weight="650"><tspan style="fill:var(--c1)">●</tspan> ${esc(o.rn)}</text>`;
    cats.forEach((c,k)=>{const y0=top+bh*k+bh*.14,h=bh*.72,a=o.l[k],b=o.r[k];const dl=`animation-delay:${k*50}ms`;
      const t1=` data-t="${tipA(c+' · '+o.ln,[[fmt(a,o.u),o.ln,2]])}"`,t2=` data-t="${tipA(c+' · '+o.rn,[[fmt(b,o.u),o.rn,1]])}"`;
      s+=E.look==='3d'?prism(xl(a),y0,cx-gw/2-xl(a),h,2,'m mh neg pr',k,dl,false,5,t1):`<path class="m mh neg${kc(2)}" data-i="${k}" d="${bp(xl(a),y0,cx-gw/2-xl(a),h,2.5,'l')}" style="fill:var(--c2);${dl}"${t1}/>`;
      s+=E.look==='3d'?prism(cx+gw/2,y0,xr(b)-cx-gw/2,h,1,'m mh pr',k,dl,false,5,t2):`<path class="m mh${kc(1)}" data-i="${k}" d="${bp(cx+gw/2,y0,xr(b)-cx-gw/2,h,2.5,'r')}" style="fill:var(--c1);${dl}"${t2}/>`;
      lab+=`<text x="${n1(cx)}" y="${n1(y0+h/2+fs*.36)}" text-anchor="middle" class="tkn">${esc(c)}</text><text x="${n1(xl(a)-4)}" y="${n1(y0+h/2+fs*.36)}" text-anchor="end" class="tk">${fmt(a,o.u)}</text><text x="${n1(xr(b)+(E.look==='3d'?9:4))}" y="${n1(y0+h/2+fs*.36)}" class="tk">${fmt(b,o.u)}</text>`;});
    lab+=`<text x="${n1(cx)}" y="${n1(H-3)}" text-anchor="middle" class="tk">${esc(o.foot||'')}</text>`;
  }else{/* sensitivity around a base */
    const rows=o.rows.slice().sort((a,b)=>(b.hi-b.lo)-(a.hi-a.lo)),n=rows.length,vals=rows.flatMap(r=>[r.lo,r.hi,o.base]);
    const lw=Math.max(...rows.map(r=>TW(r.n,fs)))+10,L=lw,R=W-xRp(Math.min(...vals),Math.max(...vals),o.u,fs,4),top=fs+14,B=H-fs-10;const ax=xXax(Math.min(...vals),Math.max(...vals),L,R,top,B,fs,o.u,4),x=ax.x,bh=(B-top)/n;g=ax.g;
    rows.forEach((r,k)=>{const y0=top+bh*k+bh*.16,h=bh*.68,dl=`animation-delay:${k*50}ms`;const tt=` data-t="${tipA(r.n,[[fmt(r.lo,o.u),'Low case ('+r.ll+')','dneg'],[fmt(r.hi,o.u),'High case ('+r.hl+')','dpos'],[fmt(r.hi-r.lo,o.u),'Swing','muted']])}"`;
      s+=`<g data-i="${k}"${tt}><path class="m mh neg${kc('dneg')}" d="${bp(x(r.lo),y0,x(o.base)-x(r.lo),h,2,'l')}" style="fill:var(--dneg);${dl}"/><path class="m mh${kc('dpos')}" d="${bp(x(o.base),y0,x(r.hi)-x(o.base),h,2,'r')}" style="fill:var(--dpos);${dl}"/></g>`;
      lab+=`<text x="${n1(L-6)}" y="${n1(y0+h/2+fs*.36)}" text-anchor="end" class="tkn">${esc(r.n)}</text>`;
      if(big)lab+=`<text x="${n1(x(r.lo)-4)}" y="${n1(y0+h/2+fs*.36)}" text-anchor="end" class="tk" font-size="${fs-1}">${esc(r.ll)}</text><text x="${n1(x(r.hi)+4)}" y="${n1(y0+h/2+fs*.36)}" class="tk" font-size="${fs-1}">${esc(r.hl)}</text>`;});
    const xb=n1(x(o.base));lab+=`<line class="tgt2" x1="${xb}" x2="${xb}" y1="${n1(top-6)}" y2="${n1(B)}"/><text x="${xb}" y="${n1(top-9)}" text-anchor="middle" class="reft">Base case ${fmt(o.base,o.u)}</text>`;}
  return svgWrap(W,H,fs,g+`<g class="gm">${s}</g>`+lab);
}};

/* ======================= Radar ======================= */
E.radar={draw(o,st,W,H){
  const fs=FS(W),multi=o.multi;
  const one=(A,ser,cx,cy,R,mini)=>{const n=A.length,mx=o.max,ang=k=>-Math.PI/2+k*Math.PI*2/n,P=(k,v)=>[cx+Math.cos(ang(k))*R*v/mx,cy+Math.sin(ang(k))*R*v/mx];let g='',s='',lab='';
    for(let l=1;l<=4;l++){const f=l/4;g+=o.grid==='circle'?`<circle class="rg" cx="${n1(cx)}" cy="${n1(cy)}" r="${n1(R*f)}"/>`:`<path class="rg" d="M${A.map((_,k)=>{const p=P(k,mx*f);return n1(p[0])+','+n1(p[1]);}).join('L')}Z"/>`;}
    A.forEach((a,k)=>{const p=P(k,mx);g+=`<line class="rs" x1="${n1(cx)}" y1="${n1(cy)}" x2="${n1(p[0])}" y2="${n1(p[1])}"/>`;if(!mini||W>=560){const q=P(k,mx*1.1),cs=Math.cos(ang(k)),sn=Math.sin(ang(k));lab+=`<text x="${n1(q[0])}" y="${n1(q[1]+fs*.36+(Math.abs(cs)<.2?(sn>0?fs*.45:-fs*.2):0))}" text-anchor="${Math.abs(cs)<.2?'middle':cs>0?'start':'end'}" class="tkn" font-size="${mini?fs-1:fs}">${esc(a)}</text>`;}});
    if(!mini)for(let l=1;l<4;l++)lab+=`<text x="${n1(cx+4)}" y="${n1(cy-R*l/4+fs-1)}" class="tk" font-size="${fs-2}">${trimN(mx*l/4,1)}</text>`;
    ser.forEach((sr,si)=>{const c=sr.c||si+1,pts=sr.v.map((v,k)=>P(k,v));
      s+=`<g data-i="${si}"><path class="ra${o.fill===false?' nofill':''}${kc(c)}" d="M${pts.map(p=>n1(p[0])+','+n1(p[1])).join('L')}Z" style="fill:${col(c)};stroke:${col(c)}"/>`;
      if(o.dots!==false)pts.forEach((p,k)=>{s+=`<circle class="dot${kc(c)}" cx="${n1(p[0])}" cy="${n1(p[1])}" r="${mini?2.4:W>=560?4.5:3.2}" style="fill:${col(c)}" data-t="${tipA(sr.n+' · '+A[k],[[trimN(sr.v[k],1)+' / '+mx,'Score',c]])}"/>`;});s+='</g>';});
    return {g,s,lab};};
  if(multi){const n=multi.length,cols=n>3?Math.ceil(n/2):n,rows=Math.ceil(n/cols),cw=W/cols,ch=H/rows;let g='',s='',lab='';
    multi.forEach((m,k)=>{const cx=cw*(k%cols+.5),cy=ch*(Math.floor(k/cols)+.5)+fs*.5,R=Math.min(cw,ch-fs*2.2)/2-(W>=560?24:6);const r=one(o.axes,m.series,cx,cy,R,true);g+=r.g;s+=r.s;lab+=r.lab+`<text x="${n1(cx)}" y="${n1(cy-R-(W>=560?20:6))}" text-anchor="middle" class="smt">${esc(m.n)}</text>`;});
    return svgWrap(W,H,fs,g+`<g class="gm">${s}</g>`+lab);}
  const lg=o.series.length>1?legendSvg(o.series.map((s,i)=>({n:s.n,c:s.c||i+1})),4,fs+1,W*.3,fs):{s:'',h:0};
  const lw=Math.max(...o.axes.map(a=>TW(a,fs)))+10,R=Math.min(H/2-fs*1.7-2,(W-lw*2)/2-6),cx=W/2,cy=H/2+2;const r=one(o.axes,o.series,cx,cy,R,false);
  return svgWrap(W,H,fs,r.g+`<g class="gm">${r.s}</g>`+r.lab+lg.s);
}};
