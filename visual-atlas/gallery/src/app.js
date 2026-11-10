/* ============================================================
   App: builds the page, renders visuals lazily, and handles
   drill, zoom, brush, pan, play, tooltips and focus mode.
   ============================================================ */
(function(){
'use strict';
const $=(s,r)=>(r||document).querySelector(s),$$=(s,r)=>[...(r||document).querySelectorAll(s)];
/* brand tokens and look must exist before the first chart is drawn */
BRAND.apply();LOOK.init();LOOK.set(BRAND.state.look||'soft');
const TILE=[360,226],FOCUS=[880,495];
let VID=0;VIS.forEach(vs=>vs.v.forEach(x=>{x._id=++VID;}));
const ST_LABEL={ga:'GA',preview:'Preview',legacy:'Legacy',retiring:'Retiring',appsource:'AppSource',build:'Build'};
const ST_TITLE={ga:'Generally available',preview:'Preview: enable it under Options › Preview features',legacy:'Legacy: kept for existing reports',retiring:'Retiring in December 2026',appsource:'From AppSource: Visualizations pane › … › Get more visuals',build:'Build it yourself with Deneb or DAX measures'};
const isExt=v=>v.st==='appsource'||v.st==='build';
const HI={
  up:'<path d="M12 19V5M6 11l6-6 6 6"/>',
  dm:'<circle cx="12" cy="12" r="9"/><path d="M12 7.5v9M8.5 13l3.5 3.5 3.5-3.5"/>',
  next:'<path d="M7 5l5 5 5-5M7 12.5l5 5 5-5"/>',
  exp:'<path d="M12 3.5v6.5M12 10l-6 6.5M12 10l6 6.5M5.5 12.5v4.5H10M18.5 12.5v4.5H14"/>',
  reset:'<path d="M4.5 12a7.5 7.5 0 1 0 2.2-5.3M4.5 4.5v4h4"/>',
  focus:'<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
  play:'<path d="M8 5.5l10.5 6.5L8 18.5z" fill="currentColor" stroke="none"/>',
  pause:'<path d="M8.5 5.5v13M15.5 5.5v13" stroke-width="2.6"/>'
};
const btn=(a,label,toggle)=>`<button type="button" data-a="${a}" aria-label="${label}" title="${label}"${toggle?' aria-pressed="false"':''}><svg viewBox="0 0 24 24">${HI[a]}</svg></button>`;
const isMap=v=>v.k==='wmap'||v.k==='usmap';
const hasDrill=v=>!!(v.o.drill||v.o.layer==='drill'||v.o.fill==='drill'||v.matrix);
function hdr(v,focus){
  let b='';
  if(hasDrill(v)){b+=btn('up','Drill up');b+=btn('dm','Drill mode: click a data point to drill down',1);if(!isMap(v)){b+=btn('next','Go to the next level in the hierarchy');b+=btn('exp','Expand all down one level in the hierarchy');}}
  if(v.zoom||v.brush||v.map)b+=btn('reset','Reset zoom');
  if(!focus)b+=btn('focus','Focus mode');
  return `<div class="vh">${b}</div>`;
}
function extras(v){
  let s='';
  if(v.zoom)s+=`<div class="zs" aria-label="Zoom slider"><div class="tr"></div><div class="win"></div><span class="h l" role="slider" aria-label="Zoom start" tabindex="0"></span><span class="h r" role="slider" aria-label="Zoom end" tabindex="0"></span></div>`;
  if(v.map)s+=`<div class="mapctl"><button type="button" data-a="zin" aria-label="Zoom in">+</button><button type="button" data-a="zout" aria-label="Zoom out">−</button></div>`;
  if(v.play)s+=`<div class="playbar"><button type="button" data-a="play" aria-label="Play">▶</button><div class="pt-track">${v.o.play.yrs.map((y,i)=>`<span data-f="${i}">${y}</span>`).join('')}</div></div>`;
  return s;
}
function initState(v){
  const st={};
  if(v.dm)st.dm=true;
  if(v.z)st.z=v.z.slice();
  if(hasDrill(v)){st.path=[];st.lvl=1;}
  if(v.st)Object.assign(st,JSON.parse(JSON.stringify(v.st)));
  return st;
}
const clone=o=>JSON.parse(JSON.stringify(o));
const plural=w=>/y$/.test(w)?w.slice(0,-1)+'ies':w+'s';

/* ---------------- instances ---------------- */
class Inst{
  constructor(vis,vi,root,focus){this.vis=vis;this.vi=vi;this.v=vis.v[vi];this.root=root;this.focus=!!focus;this.st=initState(this.v);this.rendered=false;root._inst=this;}
  get W(){return this.focus?FOCUS[0]:TILE[0];}
  get H(){return this.focus?FOCUS[1]:TILE[1];}
  get plot(){return $('.plot',this.root);}
  render(mode){
    const v=this.v,eng=E[v.k];let html;
    try{html=eng.draw(v.o,this.st,this.W,this.H);}catch(err){console.error(v.t,err);html='<div class="ph">This variation could not be drawn</div>';}
    const p=this.plot;p.innerHTML=html;this.svg=$('svg.v',p);
    if(this.svg){this.svg.setAttribute('role','img');this.svg.setAttribute('aria-label',this.vis.n+': '+v.t);if(this.st.dm)this.svg.classList.add('dm');}
    applyHL(this);this.chrome();this.rendered=true;
    if(mode==='drill'){p.classList.remove('drillin');void p.offsetWidth;p.classList.add('drillin');}
  }
  chrome(){
    const v=this.v,st=this.st,r=this.root;
    const set=(a,on,dis)=>{const b=$(`.vh [data-a="${a}"]`,r);if(!b)return;if(on!=null)b.setAttribute('aria-pressed',on?'true':'false');b.disabled=!!dis;};
    let crumb='';
    if(hasDrill(v)){
      const path=st.path||[];
      if(v.matrix){crumb=st.flat?'<b>Country</b> across all regions':path.length?`Region › <b>${MAT[path[0]].n}</b>`:'<b>Region</b>';set('up',null,!(path.length||st.flat||(st.open&&st.open.length)||(!st.open&&v.o.open&&v.o.open.length)));set('next',null,!!st.flat);set('exp',null,false);}
      else if(isMap(v)){const names=v.k==='wmap'?REG4:REGS;crumb=path.length?`${v.k==='wmap'?'World':'United States'} › <b>${names[path[0]]}</b>`:`<b>${v.k==='wmap'?'Regions':'Regions'}</b>`;set('up',null,!path.length);}
      else{const dv=drillView(v.o.drill,st);const lvls=dv.levels;
        crumb=(dv.crumb.length?dv.crumb.map(c=>`<b>${esc(c)}</b>`).join(' › ')+' › ':'')+(dv.rel>1?(st.exp?`${lvls.slice(dv.path.length,dv.lvl).join(' + ')} <span>(expanded)</span>`:`All ${plural(lvls[dv.lvl-2]).toLowerCase()} › <b>${dv.level}</b>`):`<b>${dv.level}</b>`);
        set('up',null,!(dv.path.length||dv.lvl>1));set('next',null,dv.lvl>=dv.max);set('exp',null,dv.lvl>=dv.max);}
      set('dm',!!st.dm);
      if(st.dm)crumb+=` <span class="hint">· click ${isMap(v)?'a region':v.k==='pie'?'a slice':v.k==='treemap'?'a tile':'a data point'} to drill</span>`;
    }
    const zoomed=!!(st.z||st.zx||st.zy||(st.k&&st.k>1.001)||st.tx||st.ty);
    if(v.zoom||v.brush||v.map)set('reset',null,!zoomed);
    if(!crumb&&(v.zoom||v.brush)){
      if(this.svg&&this.svg.dataset.nn&&st.z){const n=+this.svg.dataset.n,nn=+this.svg.dataset.nn;crumb=`Showing <b>${n}</b> of ${nn} · drag to zoom`;}
      else if(v.k==='scatter')crumb=st.zx?'<b>Zoomed</b> · reset from the header':'Drag a rectangle to zoom';
      else if(v.k==='gantt')crumb=st.z?'<b>Zoomed</b> · drag the timeline to zoom again':'Drag across the timeline to zoom';
      else crumb='Drag across the plot to zoom';
    }
    if(!crumb&&v.map&&!hasDrill(v))crumb=(st.k||1)>1.001?`Zoom <b>${(st.k).toFixed(1)}×</b> · drag to pan`:'Drag to pan · + and − to zoom';
    if(v.play){const f=st.f==null?v.o.play.frames.length-1:st.f;crumb=`Play axis · <b>${v.o.play.yrs[f]}</b>`;$$('.pt-track span',r).forEach((s,i)=>s.classList.toggle('on',i===f));const pb=$('.playbar button',r);if(pb){pb.textContent=this.timer?'❚❚':'▶';pb.setAttribute('aria-label',this.timer?'Pause':'Play');}}
    const c=$('.crumb',r);if(c)c.innerHTML=crumb;
    const zs=$('.zs',r);if(zs){const z=zoomFrac(this);$('.win',zs).style.cssText=`left:${z[0]*100}%;width:${(z[1]-z[0])*100}%`;$('.h.l',zs).style.left=z[0]*100+'%';$('.h.r',zs).style.left=z[1]*100+'%';}
  }
}
function zoomFrac(inst){
  const v=inst.v,st=inst.st;
  if(v.k==='scatter'){if(!st.zx)return [0,1];const m=scatterModel(v.o,{},inst.W,inst.H);return [(st.zx[0]-m.TX.lo)/(m.TX.hi-m.TX.lo),(st.zx[1]-m.TX.lo)/(m.TX.hi-m.TX.lo)];}
  return st.z||[0,1];
}
function setZoomFrac(inst,a,b){
  const v=inst.v,st=inst.st;
  if(v.k==='scatter'){const m=scatterModel(v.o,{},inst.W,inst.H);if(a<=0.001&&b>=.999){st.zx=null;st.zy=null;}else st.zx=[m.TX.lo+a*(m.TX.hi-m.TX.lo),m.TX.lo+b*(m.TX.hi-m.TX.lo)];}
  else st.z=(a<=0.001&&b>=.999)?null:[a,b];
}
function applyHL(inst){
  const s=inst.svg;if(!s)return;const h=inst.st.hl,hs=String(h);
  s.classList.toggle('hl',h!=null);
  $$('[data-i],[data-j],[data-n]',s).forEach(e=>{const on=h!=null&&(e.getAttribute('data-i')===hs||e.getAttribute('data-j')===hs||(!!e.dataset.n&&e.dataset.n.split(' ').includes(hs)));e.classList.toggle('on',on);});
}

/* ---------------- build the page ---------------- */
const totalVar=VIS.reduce((a,v)=>a+v.v.length,0);
const interactive=v=>hasDrill(v)||v.zoom||v.brush||v.map||v.play||!!E[v.k].act;
const intCount=VIS.reduce((a,vs)=>a+vs.v.filter(interactive).length,0);
const nStd=VIS.filter(v=>!isExt(v)).length,nApp=VIS.filter(v=>v.st==='appsource').length,nBuild=VIS.filter(v=>v.st==='build').length;
$('#f-vis').textContent=nStd;$('#f-ext').textContent=nApp+nBuild;$('#f-var').textContent=totalVar;$('#f-int').textContent=intCount;
$('#l-std').textContent=nStd;$('#l-ext').textContent=nApp+nBuild;$('#l-var').textContent=totalVar;
const SRCN={all:VIS.length,std:nStd,appsource:nApp,build:nBuild};$$('#srcbar button').forEach(b=>{$('span',b).textContent=SRCN[b.dataset.src];});
$('#q').placeholder=`Search ${VIS.length} visuals: sankey, drill, zoom, target…`;
$('#chips').innerHTML=QUEST.map(q=>`<button type="button" class="chip" data-goal="${q[0]}" aria-pressed="false">${q[1]}</button>`).join('');
const pill=s=>`<span class="pill ${s==='build'?'bld':s}" title="${ST_TITLE[s]}"><i></i>${ST_LABEL[s]}</span>`;
let g='',xdone=false;
CATS.forEach((c,ci)=>{
  const vs=VIS.filter(v=>v.cat===c.id);
  if(c.x&&!xdone){xdone=true;g+=`<section class="xdiv" id="beyond" data-x="1"><div><h2>Beyond the built-in pane</h2><p>${nApp+nBuild} more visuals that report builders reach for: ${nApp} from AppSource and ${nBuild} built with code. They share the same brand tokens, looks, tooltips and cross-highlighting as the built-in ones.</p></div><ol><li><span><b>Visualizations pane › … › Get more visuals</b>, then search by name</span></li><li><span>Check <b>certification</b> if your tenant allows only certified visuals</span></li><li><span>Or build one with <b>Deneb</b>, or SVG and HTML from <b>DAX measures</b></span></li></ol></section>`;}
  const srcPill=c.x?pill(vs.some(v=>v.st==='build')?'build':'appsource'):'';
  g+=`<section class="cat" id="cat-${c.id}" data-cat="${c.id}"><div class="cat-h"><span class="ix">${String(ci+1).padStart(2,'0')}</span><h2>${c.n}</h2><span class="n">${vs.length} visual${vs.length>1?'s':''} · ${vs.reduce((a,v)=>a+v.v.length,0)} variations</span>${srcPill?`<span class="src">${srcPill}</span>`:''}<p>${c.d}</p></div>`;
  vs.forEach(vis=>{
    vis._text=[vis.n,vis.best,...vis.uses,vis.avoid,...vis.v.map(x=>x.t+' '+x.d+' '+(x.tag||'')),vis.st==='appsource'?'appsource custom marketplace':vis.st==='build'?'custom code build deneb dax svg html':'built-in standard'].join(' ').toLowerCase();
    g+=`<article class="vis" id="${vis.id}" data-vis="${vis.id}"><div class="vis-h"><div class="vis-ic">${glyph(vis.ic)}</div><h3><a href="#${vis.id}">${vis.n}</a>${pill(vis.st)}</h3><p class="best">${vis.best}</p></div>
      <div class="meta"><div><h4>Field wells</h4><div class="wells">${vis.wells.map(w=>`<span class="well${w[1]?'':' empty'}"><b>${w[0]}</b><span>${w[1]?esc(w[1]):'empty'}</span></span>`).join('')}</div></div>
      <div><h4>Use it for</h4><ul>${vis.uses.map(u=>`<li>${u}</li>`).join('')}</ul><p class="avoid"><b>Avoid:</b> ${vis.avoid}</p></div></div>
      <div class="tiles">${vis.v.map((v,vi)=>`<article class="tile" data-vis="${vis.id}" data-vi="${vi}"><div class="th"><b role="button" tabindex="0" title="Open in focus mode">${esc(v.t)}</b>${v.tag?`<span class="tag t-${v.tag.replace(/\W/g,'')}">${v.tag}</span>`:''}${hdr(v,false)}</div><div class="crumb"></div><div class="tb"><div class="plot"><div class="ph">Drawing…</div></div>${extras(v)}</div><div class="tf"><p>${esc(v.d)}</p><code>${esc(v.h)}</code></div></article>`).join('')}</div></article>`;
  });
  g+='</section>';
});
$('#gallery').innerHTML=g;
const VISBY={};VIS.forEach(v=>{VISBY[v.id]=v;});
const insts=$$('.tile').map(el=>new Inst(VISBY[el.dataset.vis],+el.dataset.vi,el,false));

/* Visualizations pane */
let ph='';
let psep=false;
CATS.forEach(c=>{if(c.x&&!psep){psep=true;ph+=`<div class="pane-sep">AppSource &amp; custom<span>Get more visuals</span></div>`;}ph+=`<div class="grp">${c.n}</div><div class="icons">`+VIS.filter(v=>v.cat===c.id).map(v=>`<a href="#${v.id}" data-id="${v.id}" class="st-${v.st}" title="${v.n}${v.st!=='ga'?' ('+ST_LABEL[v.st]+')':''}" aria-label="${v.n}">${glyph(v.ic)}</a>`).join('')+'</div>';});
$('#icons').innerHTML=ph;
function showBuild(id){
  const v=VISBY[id];if(!v)return;
  $$('#icons a').forEach(a=>a.classList.toggle('on',a.dataset.id===id));
  $('#build').innerHTML=`<div class="grp">Build visual</div><div class="build-n">${glyph(v.ic)}${v.n}</div>`+v.wells.map(w=>`<div class="bw"><label>${w[0]}</label><div class="${w[1]?'':'e'}">${w[1]?esc(w[1]):'Add data fields here'}</div></div>`).join('');
}
showBuild(VIS[0].id);

/* ---------------- lazy rendering ---------------- */
const visible=el=>el.offsetParent!==null;
const ioR=new IntersectionObserver(es=>{es.forEach(e=>{if(e.isIntersecting){const i=e.target._inst;if(!i.rendered)i.render();}});},{rootMargin:'700px 0px'});
const ioP=new IntersectionObserver(es=>{es.forEach(e=>{const i=e.target._inst;if(e.isIntersecting&&!i.played){i.played=true;if(!i.rendered)i.render();const p=i.plot;p.classList.add('play');setTimeout(()=>p.classList.remove('play'),1500);ioP.unobserve(e.target);}});},{threshold:.3});
insts.forEach(i=>{ioR.observe(i.root);ioP.observe(i.root);});
let qi=0,pumping=false;
function pump(){const t0=performance.now();while(qi<insts.length&&performance.now()-t0<10){const i=insts[qi++];if(!i.rendered&&visible(i.root))i.render();}if(qi<insts.length)(window.requestIdleCallback||((f)=>setTimeout(f,30)))(pump);else pumping=false;}
function startPump(d){if(pumping)return;pumping=true;setTimeout(pump,d||0);}
startPump(250);

/* active visual tracking for the pane */
const ioA=new IntersectionObserver(es=>{es.forEach(e=>{if(e.isIntersecting)showBuild(e.target.dataset.vis);});},{rootMargin:'-35% 0px -60% 0px'});
$$('.vis').forEach(el=>ioA.observe(el));

/* ---------------- tooltip ---------------- */
const tip=$('#tip');let tipEl=null;
function buildTip(str){
  const parts=str.split('|');tip.textContent='';
  const tt=document.createElement('div');tt.className='tt';tt.textContent=parts[0];tip.appendChild(tt);
  parts.slice(1).forEach(r=>{const [val,lab,c]=r.split('~');const row=document.createElement('div');row.className='r'+(lab===''?' note':'');
    if(lab!==''){const k=document.createElement('i');k.style.background=c==='ink'?'var(--ink)':col(isNaN(+c)?c:+c);row.appendChild(k);}
    const b=document.createElement('b');b.textContent=val;row.appendChild(b);
    if(lab){const s=document.createElement('span');s.textContent=lab;row.appendChild(s);}tip.appendChild(row);});
}
function placeTip(x,y){const w=tip.offsetWidth,h=tip.offsetHeight;let left=x+14,top=y+14;if(left+w>innerWidth-8)left=x-w-14;if(top+h>innerHeight-8)top=y-h-14;tip.style.left=Math.max(8,left)+'px';tip.style.top=Math.max(8,top)+'px';}
function hideTip(){tip.classList.remove('on');tipEl=null;}
document.addEventListener('pointermove',e=>{
  if(dragging){hideTip();return;}
  const t=e.target.closest&&e.target.closest('[data-t]');
  if(!t||!t.closest('.plot')){if(tipEl)hideTip();return;}
  if(t!==tipEl){buildTip(t.getAttribute('data-t'));tipEl=t;tip.classList.add('on');}
  placeTip(e.clientX,e.clientY);
},{passive:true});
document.addEventListener('pointerdown',e=>{if(e.pointerType==='touch'){const t=e.target.closest&&e.target.closest('[data-t]');if(t&&t.closest('.plot')){buildTip(t.getAttribute('data-t'));tipEl=t;tip.classList.add('on');placeTip(e.clientX,e.clientY);}else hideTip();}},{passive:true});
addEventListener('scroll',hideTip,{passive:true});

/* ---------------- map view animation ---------------- */
function animateView(inst,to,ms){
  const st=inst.st;const fr={k:st.k||1,tx:st.tx||0,ty:st.ty||0};const t0=performance.now();ms=ms||520;
  if(inst.anim)cancelAnimationFrame(inst.anim);
  const ease=t=>t<.5?4*t*t*t:1-Math.pow(-2*t+2,3)/2;
  const step=now=>{const t=Math.min(1,(now-t0)/ms),e=ease(t);
    /* interpolate in log-zoom space so the zoom feels even */
    const k=Math.exp(Math.log(fr.k)+(Math.log(to.k)-Math.log(fr.k))*e);
    const a=(k-fr.k)/((to.k-fr.k)||1);const w=Math.abs(to.k-fr.k)<1e-6?e:Math.max(0,Math.min(1,a));
    st.k=k;st.tx=fr.tx+(to.tx-fr.tx)*w;st.ty=fr.ty+(to.ty-fr.ty)*w;inst.render();
    if(t<1)inst.anim=requestAnimationFrame(step);else{st.k=to.k;st.tx=to.tx;st.ty=to.ty;if(to.k<=1.001){st.k=1;st.tx=0;st.ty=0;}inst.render();inst.anim=null;}};
  inst.anim=requestAnimationFrame(step);
}
function zoomAt(inst,cx,cy,f){const st=inst.st;const k=st.k||1,k2=Math.max(1,Math.min(12,k*f));const tx=st.tx||0,ty=st.ty||0;return {k:k2,tx:cx-(cx-tx)*(k2/k),ty:cy-(cy-ty)*(k2/k)};}
function mapG(v){return v.k==='wmap'?GEO.world:GEO.us;}

/* ---------------- actions ---------------- */
function act(inst,a){
  const v=inst.v,st=inst.st;
  if(a==='focus')return openFocus(inst);
  if(a==='dm'){st.dm=!st.dm;inst.render();return;}
  if(a==='play')return togglePlay(inst);
  if(a==='zin'||a==='zout'){const t=zoomAt(inst,inst.W/2,inst.H/2,a==='zin'?1.7:1/1.7);animateView(inst,t,360);return;}
  if(a==='reset'){st.z=null;st.zx=null;st.zy=null;if(isMap(v)){if(st.path)st.path=[];animateView(inst,{k:1,tx:0,ty:0},420);return;}inst.render();return;}
  if(a==='up'){
    if(v.matrix){if(st.path&&st.path.length)st.path=[];else if(st.flat)st.flat=false;else st.open=[];inst.render('drill');return;}
    if(isMap(v)){if(st.path&&st.path.length){st.path=[];animateView(inst,{k:1,tx:0,ty:0});}return;}
    const path=st.path||[];
    if((st.lvl||1)>path.length+1){st.lvl--;if(st.lvl===path.length+1)st.exp=false;}else if(path.length){path.pop();st.lvl=path.length+1;st.exp=false;}
    st.z=null;st.hl=null;inst.render('drill');return;
  }
  if(a==='next'||a==='exp'){
    if(v.matrix){if(a==='next'){st.flat=true;st.path=[];}else{st.flat=false;st.path=[];st.open=MAT.map((_,i)=>i);}inst.render('drill');return;}
    const max=v.o.drill.levels.length;if((st.lvl||1)<max){st.lvl=(st.lvl||1)+1;st.exp=a==='exp';}
    st.z=null;st.hl=null;inst.render('drill');return;
  }
}
function drillInto(inst,i){
  const v=inst.v,st=inst.st;
  if(v.matrix){st.path=[i];st.flat=false;inst.render('drill');return;}
  if(isMap(v)){st.path=[i];const bb=E[v.k].bbox(v.o,st);if(bb){const t=mapFit(mapG(v),inst.W,inst.H,v.o,bb);animateView(inst,t,620);}else inst.render();return;}
  st.path=(st.path||[]).concat([i]);st.lvl=st.path.length+1;st.exp=false;st.z=null;st.hl=null;inst.render('drill');
}

/* ---------------- play axis ---------------- */
function togglePlay(inst){
  const st=inst.st,fr=inst.v.o.play.frames;
  if(inst.timer){clearInterval(inst.timer);inst.timer=null;inst.chrome();return;}
  if(st.f==null||st.f>=fr.length-1)st.f=0;
  inst.render();
  inst.timer=setInterval(()=>{if(st.f>=fr.length-1){clearInterval(inst.timer);inst.timer=null;inst.chrome();return;}st.f++;moveFrame(inst);},1050);
  inst.chrome();
}
function moveFrame(inst){
  const svg=inst.svg;if(!svg){inst.render();return;}
  const m=scatterModel(inst.v.o,inst.st,inst.W,inst.H);
  m.P.forEach(q=>{const g=svg.querySelector(`.pt[data-k="${CSS.escape(q.k)}"]`);if(!g)return;g.style.transform=`translate(${n1(q.x)}px,${n1(q.y)}px)`;const d=g.querySelector('.dot');if(d)d.setAttribute('r',n1(q.r));
    const rows=[[fmt(q.p.x,''),inst.v.o.xt,1],[fmt(q.p.y,''),inst.v.o.yt,'muted'],[fmt(q.p.s,''),inst.v.o.st||'Size','muted']];g.setAttribute('data-t',[q.p.n,...rows.map(r=>r.join('~'))].join('|'));});
  const pl=svg.querySelector('.playlab');if(pl)pl.textContent=inst.v.o.play.yrs[inst.st.f];
  inst.chrome();
}

/* ---------------- pointer interaction: brush, pan, sliders ---------------- */
let dragging=null,suppressUntil=0;const suppress=()=>{suppressUntil=performance.now()+80;};
const instOf=el=>{const r=el.closest('.tile,.fm');return r&&r._inst;};
function svgPt(svg,e){const p=svg.createSVGPoint();p.x=e.clientX;p.y=e.clientY;return p.matrixTransform(svg.getScreenCTM().inverse());}
document.addEventListener('pointerdown',e=>{
  if(e.button!==0)return;
  const zs=e.target.closest('.zs');
  if(zs){const inst=instOf(zs);if(!inst)return;e.preventDefault();const r=zs.getBoundingClientRect();const z=zoomFrac(inst);const h=e.target.classList.contains('h')?(e.target.classList.contains('l')?'l':'r'):e.target.classList.contains('win')?'w':null;
    const f0=(e.clientX-r.left)/r.width;let mode=h;if(!mode){mode=Math.abs(f0-z[0])<Math.abs(f0-z[1])?'l':'r';}
    dragging={kind:'zs',inst,r,z0:z.slice(),f0,mode};zs.setPointerCapture&&zs.setPointerCapture(e.pointerId);if(!h)moveSlider(e);return;}
  const svg=e.target.closest('.plot svg.v');if(!svg)return;const inst=instOf(svg);if(!inst)return;const v=inst.v;
  if(e.target.closest('[data-act]'))return;
  if(isMap(v)&&svg.dataset.map){const r=svg.getBoundingClientRect();const s=Math.min(r.width/inst.W,r.height/inst.H);dragging={kind:'pan',inst,svg,x:e.clientX,y:e.clientY,s,moved:false};return;}
  if(v.brush){const p=svgPt(svg,e);const pl=+svg.dataset.pl,pr=+svg.dataset.pr,pt=+(svg.dataset.pt||0),pb=+(svg.dataset.pb||inst.H);if(p.x<pl||p.x>pr||p.y<pt||p.y>pb)return;
    dragging={kind:'brush',inst,svg,p0:p,cx:e.clientX,cy:e.clientY,moved:false,two:v.k==='scatter'};}
});
function moveSlider(e){const d=dragging;const f=Math.max(0,Math.min(1,(e.clientX-d.r.left)/d.r.width));let [a,b]=d.z0;const nnS=d.inst.svg&&+d.inst.svg.dataset.nn;const minW=nnS?Math.max(.04,(d.inst.v.k==='candle'?5.2:2.2)/nnS):.05;
  if(d.mode==='l')a=Math.min(f,b-minW);else if(d.mode==='r')b=Math.max(f,a+minW);else{const dx=f-d.f0;const w=b-a;a=Math.max(0,Math.min(1-w,d.z0[0]+dx));b=a+w;}
  setZoomFrac(d.inst,Math.max(0,a),Math.min(1,b));if(!d.raf)d.raf=requestAnimationFrame(()=>{d.raf=null;d.inst.render();});}
document.addEventListener('pointermove',e=>{
  const d=dragging;if(!d)return;
  if(d.kind==='zs'){moveSlider(e);return;}
  if(d.kind==='pan'){const dx=e.clientX-d.x,dy=e.clientY-d.y;if(!d.moved&&Math.hypot(dx,dy)<4)return;d.moved=true;d.svg.classList.add('panning');
    const tx=dx/d.s,ty=dy/d.s;const lg=d.svg.querySelector('.landg'),ly=d.svg.querySelector('.layers');if(lg){if(d.t0==null)d.t0=lg.getAttribute('transform')||'';lg.setAttribute('transform',`translate(${tx},${ty}) ${d.t0}`);}if(ly)ly.setAttribute('transform',`translate(${tx},${ty})`);d.dx=tx;d.dy=ty;return;}
  if(d.kind==='brush'){if(!d.moved&&Math.hypot(e.clientX-d.cx,e.clientY-d.cy)<6)return;d.moved=true;const p=svgPt(d.svg,e);const svg=d.svg;
    if(!d.rect){d.rect=document.createElementNS('http://www.w3.org/2000/svg','rect');d.rect.setAttribute('class','brush');svg.appendChild(d.rect);}
    const pl=+svg.dataset.pl,pr=+svg.dataset.pr,pt=+(svg.dataset.pt||0),pb=+(svg.dataset.pb||d.inst.H);
    const x0=Math.max(pl,Math.min(d.p0.x,p.x)),x1=Math.min(pr,Math.max(d.p0.x,p.x));const y0=d.two?Math.max(pt,Math.min(d.p0.y,p.y)):pt,y1=d.two?Math.min(pb,Math.max(d.p0.y,p.y)):pb;
    d.box=[x0,y0,x1,y1];d.rect.setAttribute('x',x0);d.rect.setAttribute('y',y0);d.rect.setAttribute('width',Math.max(0,x1-x0));d.rect.setAttribute('height',Math.max(0,y1-y0));}
});
document.addEventListener('pointerup',e=>{
  const d=dragging;if(!d)return;dragging=null;
  if(d.kind==='zs'){d.inst.render();return;}
  if(d.kind==='pan'){d.svg.classList.remove('panning');if(d.moved){suppress();const st=d.inst.st;st.tx=(st.tx||0)+(d.dx||0);st.ty=(st.ty||0)+(d.dy||0);if((st.k||1)<=1.001&&!st.path?.length){/* allow panning at 1x but keep it bounded */}d.inst.render();}return;}
  if(d.kind==='brush'&&d.moved&&d.box){suppress();const inst=d.inst,svg=d.svg,st=inst.st,v=inst.v;const [x0,y0,x1,y1]=d.box;if(x1-x0<4){inst.render();return;}
    const pl=+svg.dataset.pl,pr=+svg.dataset.pr;
    if(svg.dataset.nn){const n=+svg.dataset.n,z0=+svg.dataset.z0,nn=+svg.dataset.nn,bw=(pr-pl)/n;let ja=Math.max(0,Math.floor((x0-pl)/bw)),jb=Math.min(n-1,Math.floor((x1-pl)/bw-1e-6));if(jb-ja<1)jb=Math.min(n-1,ja+1);if(jb-ja<1)ja=Math.max(0,jb-1);st.z=[(z0+ja)/nn,(z0+jb+1)/nn];}
    else if(v.k==='gantt'){const c=st.z||[0,1];const fa=(x0-pl)/(pr-pl),fb=(x1-pl)/(pr-pl);st.z=[c[0]+fa*(c[1]-c[0]),c[0]+fb*(c[1]-c[0])];}
    else if(v.k==='scatter'){const X0=+svg.dataset.x0,X1=+svg.dataset.x1,Y0=+svg.dataset.y0,Y1=+svg.dataset.y1,pt=+svg.dataset.pt,pb=+svg.dataset.pb;st.zx=[X0+(x0-pl)/(pr-pl)*(X1-X0),X0+(x1-pl)/(pr-pl)*(X1-X0)];st.zy=[Y0+(pb-y1)/(pb-pt)*(Y1-Y0),Y0+(pb-y0)/(pb-pt)*(Y1-Y0)];}
    inst.render('drill');}
});
document.addEventListener('pointercancel',()=>{if(dragging&&dragging.svg)dragging.svg.classList.remove('panning');dragging=null;});
/* wheel zoom on maps: in focus mode, or with Ctrl/⌘ on tiles */
document.addEventListener('wheel',e=>{
  const svg=e.target.closest&&e.target.closest('.plot svg.map');if(!svg)return;const inst=instOf(svg);if(!inst)return;
  if(!inst.focus&&!(e.ctrlKey||e.metaKey))return;e.preventDefault();
  const p=svgPt(svg,e);const t=zoomAt(inst,p.x,p.y,Math.exp(-e.deltaY*.0022));Object.assign(inst.st,t);if(t.k<=1.001){inst.st.k=1;inst.st.tx=0;inst.st.ty=0;}
  if(!inst.wraf)inst.wraf=requestAnimationFrame(()=>{inst.wraf=null;inst.render();});
},{passive:false});

/* ---------------- clicks ---------------- */
document.addEventListener('click',e=>{
  if(performance.now()<suppressUntil){e.preventDefault();return;}
  const t=e.target;
  const chip=t.closest('.chip');if(chip){goal=chip.getAttribute('aria-pressed')==='true'?null:chip.dataset.goal;$$('.chip').forEach(c=>c.setAttribute('aria-pressed',String(c.dataset.goal===goal)));applyFilter();return;}
  const hb=t.closest('[data-a]');
  if(hb){const inst=instOf(hb);if(inst){e.preventDefault();act(inst,hb.dataset.a);}return;}
  const title=t.closest('.tile .th b');if(title){openFocus(instOf(title));return;}
  const fspan=t.closest('.pt-track span');if(fspan){const inst=instOf(fspan);if(inst){if(inst.timer){clearInterval(inst.timer);inst.timer=null;}inst.st.f=+fspan.dataset.f;inst.svg?moveFrame(inst):inst.render();}return;}
  const plot=t.closest('.plot');if(!plot)return;const inst=instOf(plot);if(!inst)return;
  const v=inst.v,st=inst.st;
  const a=t.closest('[data-act]');
  if(a){const [verb,...rest]=a.dataset.act.split(':');const eng=E[v.k];const r=eng.act&&eng.act(v.o,st,verb,rest.join(':'),e,a);if(r){hideTip();inst.render(r==='drill'?'drill':undefined);}e.stopPropagation();return;}
  const z=t.closest('[data-z]');if(z){const [x,y]=z.dataset.z.split(',').map(Number);animateView(inst,zoomAt(inst,x,y,2.4),480);return;}
  const d=t.closest('[data-d]');
  if(d&&st.dm){drillInto(inst,+d.dataset.d);return;}
  if(v.matrix&&st.dm){const row=t.closest('tr[data-i]');if(row&&!(st.path&&st.path.length)&&!st.flat){drillInto(inst,+row.dataset.i);return;}}
  const m=t.closest('[data-i]');
  if(m&&inst.svg&&inst.svg.contains(m)){const i=m.getAttribute('data-i');st.hl=st.hl==i?null:i;applyHL(inst);return;}
  if(inst.svg&&st.hl!=null){st.hl=null;applyHL(inst);}
});
document.addEventListener('keydown',e=>{
  const t=e.target;
  if((e.key==='Enter'||e.key===' ')&&t.matches&&t.matches('.tile .th b')){e.preventDefault();openFocus(instOf(t));return;}
  if(t.matches&&t.matches('.zs .h')&&(e.key==='ArrowLeft'||e.key==='ArrowRight')){e.preventDefault();const inst=instOf(t);const z=zoomFrac(inst);const dx=e.key==='ArrowLeft'?-.04:.04;const l=t.classList.contains('l');let a=z[0],b=z[1];if(l)a=Math.max(0,Math.min(b-.05,a+dx));else b=Math.min(1,Math.max(a+.05,b+dx));setZoomFrac(inst,a,b);inst.render();return;}
  if($('#fm').open&&!(t.tagName==='TEXTAREA'||(t.tagName==='INPUT'&&t.type!=='checkbox'))){if(e.key==='ArrowRight'){e.preventDefault();stepFocus(1);}if(e.key==='ArrowLeft'){e.preventDefault();stepFocus(-1);}}
});

/* ---------------- focus mode ---------------- */
const fm=$('#fm');let fmInst=null,fmFrom=null;
function openFocus(inst){
  if(!inst)return;hideTip();fmFrom=inst;
  if(inst.timer){clearInterval(inst.timer);inst.timer=null;}
  fm.showModal?fm.showModal():fm.setAttribute('open','');
  loadFocus(inst.vis,inst.vi,clone(inst.st));
}
function loadFocus(vis,vi,st){
  const v=vis.v[vi];
  if(fmInst&&fmInst.timer){clearInterval(fmInst.timer);fmInst.timer=null;}
  $('.fm-ti span',fm).textContent=vis.n+' · '+(vi+1)+' of '+vis.v.length;
  $('.fm-ti b',fm).textContent=v.t;
  $('.fm-vh',fm).innerHTML=hdr(v,true).replace('<div class="vh">','').replace(/<\/div>$/,'');
  $('.fm-main .tb',fm).innerHTML=`<div class="plot"></div>${extras(v)}`;
  $('.fm-d',fm).textContent=v.d;
  $('.fm-h',fm).innerHTML=v.h.split(' · ').map(s=>`<li>${esc(s)}</li>`).join('');
  $('.fm-w',fm).innerHTML=vis.wells.map(w=>`<span class="well${w[1]?'':' empty'}"><b>${w[0]}</b><span>${w[1]?esc(w[1]):'empty'}</span></span>`).join('');
  $('.fm-u',fm).innerHTML=vis.uses.map(u=>`<li>${u}</li>`).join('');
  $('.fm-nav span',fm).textContent=(vi+1)+' / '+vis.v.length;
  fm._inst=null;fmInst=new Inst(vis,vi,fm,true);if(st)fmInst.st=st;
  const cb=$('#fm-table');cb.checked=false;$('.fm-tbl',fm).hidden=true;$('.fm-main .tb',fm).hidden=false;
  const can=!!tableFor(v,fmInst.st);cb.disabled=!can;$('.fm-tt',fm).classList.toggle('dis',!can);
  $('.fm-keys',fm).innerHTML=focusHint(v);
  fmInst.render();const p=fmInst.plot;p.classList.add('play');setTimeout(()=>p.classList.remove('play'),1400);
}
function focusHint(v){const k=[];if(hasDrill(v))k.push('Turn on drill mode, then click to drill; ↑ goes back up.');if(E[v.k].act&&!hasDrill(v)&&!v.zoom)k.push('Use the controls inside the visual: click to expand, zoom or select.');if(v.brush)k.push('Drag across the plot to zoom.');if(v.map)k.push('Scroll to zoom the map, drag to pan.');if(v.play)k.push('Press play or pick a year.');k.push('<kbd>←</kbd> <kbd>→</kbd> step through variations · <kbd>Esc</kbd> closes.');return k.join(' ');}
function stepFocus(d){if(!fmInst)return;const vis=fmInst.vis;const vi=(fmInst.vi+d+vis.v.length)%vis.v.length;const tile=insts.find(i=>i.vis===vis&&i.vi===vi);loadFocus(vis,vi,tile?clone(tile.st):null);fmFrom=tile||fmFrom;}
fm.addEventListener('close',()=>{
  if(fmInst&&fmInst.timer){clearInterval(fmInst.timer);fmInst.timer=null;}
  const tile=fmInst&&insts.find(i=>i.vis===fmInst.vis&&i.vi===fmInst.vi);
  if(tile){tile.st=clone(fmInst.st);tile.st.f=fmInst.st.f;tile.render();}
  fmInst=null;
});
$('.fm-x',fm).addEventListener('click',()=>fm.close());
fm.addEventListener('click',e=>{if(e.target===fm)fm.close();});
$('.fm-prev',fm).addEventListener('click',()=>stepFocus(-1));
$('.fm-next',fm).addEventListener('click',()=>stepFocus(1));
$('#fm-table').addEventListener('change',e=>{const on=e.target.checked;const box=$('.fm-tbl',fm);if(on){box.innerHTML=tableFor(fmInst.v,fmInst.st)||'';}box.hidden=!on;$('.fm-main .tb',fm).hidden=on;});
function tableFor(v,st){
  const o=v.o;const T=(head,rows)=>`<table class="tbl"><thead><tr>${head.map((h,i)=>`<th class="${i?'':'tl'}">${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr>${r.map((c,i)=>`<td class="${i?'':'tl'}">${esc(c)}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
  if(v.k==='cart'){const R=resolve(o,st);const ser=o.layers.flatMap(L=>L.s.map(s=>({s,L})));
    return T([R.dv?R.dv.level:'Category',...ser.map(x=>x.s.n+(x.s.f?' (forecast)':''))],R.cats.map((c,i)=>[(R.grp&&R.grp[i]?R.grp[i]+' · ':'')+c,...ser.map(x=>{const val=R.get(x.s)[i];return val==null&&x.s.f?fmt(x.s.f[i],o.u):fmt(val,x.L.y2?o.u2:o.u);})]));}
  if(v.k==='sm'){const ser=o.panels[0].layers.flatMap(L=>L.s);return T(['Panel','Category',...ser.map(s=>s.n)],o.panels.flatMap(p=>p.cats.map((c,i)=>[p.n,c,...p.layers.flatMap(L=>L.s.map(s=>fmt(s.v[i],o.u)))])));}
  if(v.k==='pie'||v.k==='treemap'){if(o.nest)return T(['Category','Subcategory','Sales'],SUBS.map(s=>[s.cat,s.n,fmt(s.v[0],'$')]));if(o.ring)return T(['Part','Value'],[[o.ring[0],o.ring[1]+'%'],[o.ring[2],o.ring[3]+'%']]);const R=resolve(o,st);const vals=R.cats.map((c,i)=>R.dv?R.dv.vals[i][o.k||0]:o.v[i]);const t=sumA(vals);return T([R.dv?R.dv.level:'Category','Value','Share'],R.cats.map((c,i)=>[c,fmt(vals[i],o.u),(vals[i]/t*100).toFixed(1)+'%']));}
  if(v.k==='funnel')return T(['Stage','Count','% of first','% of previous'],o.stages.map((s,i)=>[s.n,fmt(s.v),(s.v/o.stages[0].v*100).toFixed(1)+'%',i?(s.v/o.stages[i-1].v*100).toFixed(1)+'%':'–']));
  if(v.k==='wfall'){let cur=0;return T(['Step','Change','Running total'],o.steps.map(s=>{if(s.t){cur=s.v!=null?s.v:cur;return [s.n,'Total',fmt(cur,'$')];}cur+=s.v;return [s.n,fmtS(s.v,'$'),fmt(cur,'$')];}));}
  if(v.k==='ribbon')return T(['Period',...o.s],o.cats.map((c,p)=>[c,...o.s.map((_,i)=>fmt(o.v[i][p]))]));
  if(v.k==='scatter'){const m=scatterModel(o,st,FOCUS[0],FOCUS[1]);return T(['Point',o.xt||'X',o.yt||'Y'].concat(o.size?[o.st||'Size']:[]),m.P.map(q=>[q.p.n,o.dot?o.dot.cats[q.p.c]:fmt(q.p.x,o.ux),fmt(q.p.y,o.uy)].concat(o.size?[fmt(q.p.s,o.us)]:[])));}
  if(v.k==='wmap')return T(['Location','Sales'],worldPoints(o,st).map(p=>[p.n,fmt(p.v,'$')]));
  if(v.k==='usmap'||v.k==='hexmap')return T(['State','Sales','YoY growth','Region'],GEO.us.states.map(s=>[s.n,fmt(US[s.a].s,'$'),fmtS(US[s.a].g,'%'),US[s.a].r]));
  if(v.k==='gantt')return T(['Phase','Task','Start','End','Complete'],GANTT.map(t=>[t.g,t.n,fmtD(t.s),t.e==null?'Milestone':fmtD(t.e),Math.round(t.p*100)+'%']));
  if(v.k==='sankey')return T(['From','To','Value'],o.links.map(l=>[o.nodes[l.s].n,o.nodes[l.t].n,fmt(l.v,o.u)]));
  if(v.k==='chord')return T(['From ╲ To',...o.names],o.names.map((n,i)=>[n,...o.m[i].map((x,j)=>i===j?'–':fmt(x,o.u))]));
  if(v.k==='net')return T(['Product','Category','Sales','Linked products'],NET.nodes.map(d=>[d.n,CAT4[d.g],fmt(d.v,'$'),String(d.deg)]));
  if(v.k==='org')return T(['Name','Role','Reports to'],o.people.map(p=>[p.n,p.t,p.p==null?'–':o.people[p.p].n]));
  if(v.k==='htree'||v.k==='sunburst'||v.k==='pack')return T(['Category','Subcategory','Sales'],SUBS.map(q=>[q.cat,q.n,fmt(q.v[0],'$')]));
  if(v.k==='hist')return T(['Group','Orders','Mean','Median','Lowest','Highest'],o.groups.map(g=>{const S=xStats(g.v);return [g.n,String(S.n),...[S.mean,S.md,S.min,S.max].map(x=>fmt(x,o.u))];}));
  if(v.k==='box'||v.k==='violin')return T(['Group','Count','Lowest','Q1','Median','Q3','Highest','Mean'],o.groups.map(g=>{const S=xStats(g.v);return [g.n,String(S.n),...[S.min,S.q1,S.md,S.q3,S.max,S.mean].map(x=>trimN(x,1))];}));
  if(v.k==='bullet')return T(['Measure','Actual','Target','% of target'],o.items.map(d=>[d.n,fmt(d.v,d.u),fmt(d.t,d.u),Math.round(d.v/d.t*100)+'%']));
  if(v.k==='parcoord')return T(['Subcategory',...o.dims.map(d=>d.n)],o.rows.map(r=>[r.n,...r.v.map((x,k)=>fmt(x,o.dims[k].u))]));
  if(v.k==='lolli')return T(['Category','Value'],o.cats.map((c,i)=>[c,o.div?fmtS(o.v[i],o.u):fmt(o.v[i],o.u)]));
  if(v.k==='dumbbell')return o.range?T(['Subcategory','Lowest','Average','Highest'],o.rows.map(r=>[r.n,fmt(r.lo,o.u),fmt(r.mid,o.u),fmt(r.hi,o.u)])):T(['Country',o.an,o.bn,'Change'],o.rows.map(r=>[r.n,fmt(r.a,o.u),fmt(r.b,o.u),fmtS((r.b/r.a-1)*100,'%')]));
  if(v.k==='slope')return T(['Item',o.an,o.bn],o.rows.map(r=>[r.n,fmt(r.a,o.u),fmt(r.b,o.u)]));
  if(v.k==='bump')return T(['Subcategory',...o.periods],o.series.map(q=>[q.n,...q.r.map(r=>'#'+r)]));
  if(v.k==='tornado')return o.base==null?T(['Group',o.ln,o.rn],o.cats.map((c,i)=>[c,fmt(o.l[i],o.u),fmt(o.r[i],o.u)])):T(['Driver','Low case','High case','Swing'],o.rows.map(r=>[r.n+' ('+r.ll+' / '+r.hl+')',fmt(r.lo,o.u),fmt(r.hi,o.u),fmt(r.hi-r.lo,o.u)]));
  if(v.k==='radar'){const ser=o.multi?o.multi.flatMap(m=>m.series):o.series;return T(['Series',...o.axes],ser.map(q=>[q.n,...q.v.map(String)]));}
  if(v.k==='mekko')return T(['Region',...o.segs,'Total'],o.cols.map((c,j)=>[c,...o.segs.map((_,i)=>fmt(o.m[i][j],o.u)),fmt(sumA(o.segs.map((_,i)=>o.m[i][j])),o.u)]));
  if(v.k==='waffle')return o.parts?T(['Category','Value'],o.parts.map(p=>[p.n,fmt(p.v,o.u)])):o.items?T(['Group','Share'],o.items.map(i=>[i.n,i.pct+'%'])):T(['Measure','Value'],[[o.n,o.pct+'%']]);
  if(v.k==='picto'&&o.rows)return T(['Region','Customers'],o.rows.map(r=>[r.n,fmt(r.v,o.u)]));
  if(v.k==='aster')return T(['Attribute','Score','Weight'],o.items.map(d=>[d.n,String(d.s),String(d.w)]));
  if(v.k==='rose')return T(['Month',...o.series.map(q=>q.n)],o.cats.map((c,k)=>[c,...o.series.map(q=>fmt(q.v[k],o.u))]));
  if(v.k==='venn')return T(['Group','Customers'],o.sets.map(q=>[q.n,fmt(q.v)]).concat(Object.entries(o.ov).map(([k,x])=>[k.split('').map(ch=>o.sets['abc'.indexOf(ch)].n).join(' ∩ '),fmt(x)])));
  if(v.k==='words')return T(['Phrase','Mentions','Sentiment'],o.words.map(w=>[w.t,String(w.v),w.s>0?'Positive':w.s<0?'Negative':'Neutral']));
  if(v.k==='cal'){const m=MON.map(n=>[n,0]);o.days.forEach((x,k)=>{m[xDate(k).getUTCMonth()][1]+=x;});return T(['Month','Orders'],m.map(r=>[r[0],fmt(r[1])]));}
  if(v.k==='heatgrid')return T(['Day',...o.cols],o.rows.map((r,i)=>[r,...o.m[i].map(x=>fmt(x))]));
  if(v.k==='stream')return T(['Month',...o.series.map(q=>q.n)],o.cats.map((c,k)=>[c,...o.series.map(q=>fmt(q.v[k],o.u))]));
  if(v.k==='candle')return T(['Day','Open','High','Low','Close'],o.data.map(d=>[d.d,fmt(d.o,o.u),fmt(d.h,o.u),fmt(d.l,o.u),fmt(d.c,o.u)]));
  if(v.k==='timeline')return T(['Month','Sales'],o.months.map((m,k)=>[MON[k%12]+' '+(2024+Math.floor(k/12)),fmt(o.v[k],'$')]));
  if(v.k==='liquid')return T(['Gauge','Value'],(o.items||[]).map(i=>[i.n,Math.round(i.v*100)+'%']));
  if(v.k==='radial')return o.mode==='columns'?T(['Month','Sales'],o.cats.map((c,k)=>[c,fmt(o.v[k],o.u)])):T(['Measure','% of target'],o.items.map(i=>[i.n,Math.round(i.v*100)+'%']));
  if(v.k==='tacho')return T(['Measure','Value','Target'],[[o.n,fmt(o.v,o.u),o.target!=null?fmt(o.target,o.u):'–']]);
  if(v.k==='deneb')return o.series?T(['Month',...o.series.map(q=>q.n)],o.cats.map((c,k)=>[c,...o.series.map(q=>fmt(q.v[k],'$'))])):o.v?T(['Month','Sales'],o.cats.map((c,k)=>[c,fmt(o.v[k],'$')])):T(['Month','Median orders a day'],o.rows.map(r=>[r.n,fmt(xStats(r.v).md)]));
  return null;
}

/* ---------------- search and question filters ---------------- */
let goal=null,src='all';const q=$('#q');
const SRCL={std:'built-in',appsource:'from AppSource',build:'you build yourself'};
function applyFilter(){
  const s=q.value.trim().toLowerCase();let n=0;
  VIS.forEach(vs=>{const el=document.getElementById(vs.id);const okS=src==='all'||(src==='std'?!isExt(vs):vs.st===src);const ok=okS&&(!s||vs._text.includes(s)||s.split(/\s+/).every(w=>vs._text.includes(w)))&&(!goal||vs.goals.includes(goal));el.hidden=!ok;if(ok)n++;const ic=$(`#icons a[data-id="${vs.id}"]`);if(ic)ic.hidden=!ok;});
  $$('.cat').forEach(c=>{c.hidden=!$$('.vis',c).some(v=>!v.hidden);});
  const bx=$('#beyond');if(bx)bx.hidden=!VIS.some(vs=>isExt(vs)&&!document.getElementById(vs.id).hidden);
  const fb=$('#filterbar');
  if(s||goal||src!=='all'){fb.innerHTML=`Showing <b>${n}</b> of ${VIS.length} visuals${src!=='all'?' '+SRCL[src]:''}${goal?' for “'+QUEST.find(x=>x[0]===goal)[1].toLowerCase()+'”':''}${s?' matching “'+esc(s)+'”':''} <button type="button" id="clear">Clear</button>`;}else fb.textContent='';
  $('#empty').hidden=n>0;
  insts.forEach(i=>{if(!i.rendered&&visible(i.root)){ioR.unobserve(i.root);ioR.observe(i.root);}});
}
q.addEventListener('input',applyFilter);
function setSrc(v){src=v;$$('#srcbar button').forEach(x=>x.setAttribute('aria-pressed',String(x.dataset.src===v)));}
$('#srcbar').addEventListener('click',e=>{const b=e.target.closest('button[data-src]');if(!b)return;setSrc(b.dataset.src);applyFilter();});
document.addEventListener('click',e=>{if(e.target.id==='clear'){q.value='';goal=null;setSrc('all');$$('.chip').forEach(c=>c.setAttribute('aria-pressed','false'));applyFilter();}});

/* ---------------- theme and palette ---------------- */
const root=document.documentElement;
const store={get(k){try{return localStorage.getItem(k);}catch(e){return null;}},set(k,v){try{localStorage.setItem(k,v);}catch(e){}}};
let studioReady=false;
function setTheme(t){if(t==='auto')root.removeAttribute('data-theme');else root.setAttribute('data-theme',t);$$('#theme button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.t===t)));store.set('atlas-theme',t);if(studioReady)syncStudio();}
$$('#theme button').forEach(b=>b.addEventListener('click',()=>setTheme(b.dataset.t)));
setTheme(store.get('atlas-theme')||(root.getAttribute('data-theme')||'auto'));
try{matchMedia('(prefers-color-scheme: dark)').addEventListener('change',()=>{if(studioReady)syncStudio();});}catch(e){}

/* ---------------- theme studio: brand color, palette, look ---------------- */
const MODES=[['spectrum','Spectrum'],['analogous','Analogous'],['mono','Mono'],['atlas','Atlas'],['classic','Classic'],['custom','Custom']];
const sw=(t,n)=>`<div class="st-sw">${Array.from({length:n},(_,i)=>`<i style="--sw:var(--${t}${i+1})"></i>`).join('')}</div>`;
function studioHTML(){
  return `<div class="st-h"><div><b>Theme studio</b><span>Every chart on the page reads its colors from these tokens.</span></div><button type="button" class="st-reset" data-sx="reset">Reset</button></div>
  <div class="st-g">
    <div class="st-f"><span class="st-l">Brand</span><div class="st-brand"><label class="st-pick" title="Pick a brand color"><input type="color" data-sx="pick" aria-label="Brand color"><span></span></label><input class="st-hex" data-sx="hex" spellcheck="false" autocomplete="off" maxlength="7" aria-label="Brand color as a hex code"><div class="st-seeds">${BRAND.SEEDS.map(c=>`<button type="button" data-sx="seed" data-v="${c}" style="--sw:${c}" aria-label="Use ${c}" aria-pressed="false"></button>`).join('')}</div></div></div>
    <div class="st-f"><span class="st-l">Palette</span><div class="seg st-seg" role="group" aria-label="Palette">${MODES.map(([k,t])=>`<button type="button" data-sx="mode" data-v="${k}" aria-pressed="false">${t}</button>`).join('')}</div></div>
    <div class="st-f st-cust" hidden><span class="st-l">Colors</span><textarea data-sx="custom" rows="2" spellcheck="false" placeholder="Paste hex codes, or a whole Power BI theme JSON" aria-label="Your colors"></textarea></div>
    <div class="st-f"><span class="st-l">Look</span><div class="seg st-seg" role="group" aria-label="Look">${[['flat','Flat'],['soft','Soft'],['3d','3D']].map(([k,t])=>`<button type="button" data-sx="look" data-v="${k}" aria-pressed="false">${t}</button>`).join('')}</div></div>
  </div>
  <div class="st-strip" aria-hidden="true"><div><span>Categorical</span>${sw('c',8)}</div><div><span>Sequential</span>${sw('s',7)}</div><div><span>Diverging</span>${sw('dv',5)}</div></div>
  <div class="st-foot"><span class="st-chk"></span><button type="button" class="st-copy" data-sx="copy">Copy theme JSON</button></div>
  <textarea class="st-json" readonly hidden aria-label="Power BI theme JSON"></textarea>`;
}
$$('[data-studio]').forEach(el=>{el.innerHTML=studioHTML();});
const isDark=()=>root.getAttribute('data-theme')==='dark'||(root.getAttribute('data-theme')!=='light'&&matchMedia('(prefers-color-scheme: dark)').matches);
function checkText(){
  const r=BRAND.check(isDark()),m=BRAND.state.mode,d=`ΔE ${r.n}, color-blind ΔE ${r.c}`;
  if(r.n>=15&&r.c>=8)return {cls:'ok',icon:'✓',t:`Neighboring colors stay distinct, also for color-blind readers (${d}).`};
  if(m==='mono')return {cls:'warn',icon:'!',t:`Shades of one hue work best for up to four series (${d}).`};
  if(r.c>=6&&r.n>=10)return {cls:'warn',icon:'!',t:`Some neighbors are close for color-blind readers; keep legends and labels on (${d}).`};
  return {cls:'warn',icon:'!',t:`Two neighboring colors are hard to tell apart (${d}). Reorder them or try Spectrum.`};
}
function syncStudio(){
  const st=BRAND.state,brand=BRAND.norm(st.brand),fixed=['atlas','classic','custom'].includes(st.mode),ck=checkText();
  $$('[data-studio]').forEach(el=>{
    $('[data-sx="pick"]',el).value=brand;$('.st-pick span',el).style.background=brand;
    const hx=$('[data-sx="hex"]',el);if(document.activeElement!==hx){hx.value=brand.toUpperCase();hx.removeAttribute('aria-invalid');}
    $$('[data-sx="seed"]',el).forEach(b=>b.setAttribute('aria-pressed',String(!fixed&&b.dataset.v===brand)));
    $$('[data-sx="mode"]',el).forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.v===st.mode)));
    $('.st-cust',el).hidden=st.mode!=='custom';
    const ta=$('[data-sx="custom"]',el);if(document.activeElement!==ta)ta.value=st.custom||'';
    const c=$('.st-chk',el);c.className='st-chk '+ck.cls;c.innerHTML=`<i aria-hidden="true">${ck.icon}</i><span>${ck.t}</span>`;});
  $$('[data-sx="look"]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.v===E.look)));
}
function setBrand(hex){if(!BRAND.valid(hex))return;const m=BRAND.state.mode;BRAND.set({brand:BRAND.norm(hex),mode:['atlas','classic','custom'].includes(m)?'spectrum':m});syncStudio();}
const parseCustom=v=>{try{const j=JSON.parse(v);if(j&&Array.isArray(j.dataColors))return j.dataColors.join(' ');}catch(e){}return v;};
function setLook(l){if(!['flat','soft','3d'].includes(l))l='soft';const prev=E.look;LOOK.set(l);BRAND.state.look=l;store.set('atlas-brand',JSON.stringify(BRAND.state));syncStudio();if(prev!==l)redrawAll();}
function redrawAll(){
  const vh=innerHeight;
  insts.forEach(i=>{if(!i.rendered)return;const r=i.root.getBoundingClientRect();if(visible(i.root)&&r.bottom>-500&&r.top<vh+500)i.render();else i.rendered=false;});
  if(fmInst)fmInst.render();renderMini();qi=0;startPump(120);
}
document.addEventListener('input',e=>{const t=e.target,k=t.dataset&&t.dataset.sx;if(!k)return;
  if(k==='pick')setBrand(t.value);
  else if(k==='hex'){const ok=BRAND.valid(t.value);t.setAttribute('aria-invalid',String(!ok));if(ok)setBrand(t.value);}
  else if(k==='custom'){BRAND.set({custom:parseCustom(t.value)});syncStudio();}});
document.addEventListener('click',e=>{const b=e.target.closest('button[data-sx]');if(!b)return;const k=b.dataset.sx,v=b.dataset.v;
  if(k==='seed')setBrand(v);
  else if(k==='mode'){BRAND.set({mode:v});syncStudio();if(v==='custom'){const ta=$('[data-sx="custom"]',b.closest('.studio'));if(ta)ta.focus();}}
  else if(k==='look')setLook(v);
  else if(k==='reset'){BRAND.set({brand:'#2a78d6',mode:'atlas',custom:''});setLook('soft');syncStudio();}
  else if(k==='copy'){const txt=BRAND.themeJSON(),ta=$('.st-json',b.closest('.studio'));
    const done=ok=>{b.textContent=ok?'Copied':'Copy it from the box below';setTimeout(()=>{b.textContent='Copy theme JSON';},2000);};
    const fallback=()=>{ta.hidden=false;ta.value=txt;ta.focus();ta.select();done(false);};
    try{navigator.clipboard.writeText(txt).then(()=>{ta.hidden=true;done(true);},fallback);}catch(err){fallback();}}});
studioReady=true;syncStudio();

/* studio popover in the top bar */
const pop=$('#studio-pop'),bbtn=$('#brand-btn');
const closePop=f=>{pop.hidden=true;bbtn.setAttribute('aria-expanded','false');if(f)bbtn.focus();};
bbtn.addEventListener('click',()=>{const open=pop.hidden;pop.hidden=!open;bbtn.setAttribute('aria-expanded',String(open));});
document.addEventListener('pointerdown',e=>{if(!pop.hidden&&!pop.contains(e.target)&&!bbtn.contains(e.target))closePop();});
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!pop.hidden)closePop(true);});

/* hero stage: a small report drawn by the same engine */
const MINI_SK={u:'',vn:'Sessions',nodes:[{n:'Search',col:0,c:1},{n:'Social',col:0,c:2},{n:'Email',col:0,c:3},{n:'Product',col:1,c:4},{n:'Home',col:1,c:5},{n:'Purchase',col:2,c:'dpos'},{n:'Bounce',col:2,c:'muted-mark'}],
  links:[[0,3,52],[0,4,24],[1,3,18],[1,4,22],[2,3,16],[2,4,6],[3,5,40],[3,6,46],[4,5,12],[4,6,40]].map(([s,t,v])=>({s,t,v}))};
function renderMini(){
  const put=(k,html)=>{const el=$(`[data-mini="${k}"]`);if(el)el.innerHTML=html;};
  try{
    put('kpi',`<div class="mk"><span class="mk-l">Sales 2025</span><b class="mk-v">${fmt(TYS,'$')}</b><span class="mk-d">▲ ${pctCh(TYS,LYS).toFixed(1)}% vs 2024</span><div class="mk-s">${spark(TY,{w:160,h:40,c:1})}</div></div>`);
    put('cols',E.cart.draw({cats:MON.map(m=>m.slice(0,1)),layers:[B([S('Sales',TY)])],u:'$'},{},340,150));
    put('donut',E.pie.draw({cats:CAT4,v:CAT4S,inner:.58,center:true,cl:'Sales',u:'$',legend:'bottom'},{},200,210));
    put('sankey',E.sankey.draw(MINI_SK,{},340,124));
    put('liquid',E.liquid.draw({items:[{n:'Q4 goal',v:.72,c:1}],vn:'of goal'},{},150,170));
  }catch(err){console.error('stage',err);}
}
renderMini();
const deck=$('#deck'),stage=$('#stage'),hero=$('.hero');
if(deck&&!matchMedia('(prefers-reduced-motion: reduce)').matches){let raf=0;
  hero.addEventListener('pointermove',e=>{if(e.pointerType==='touch')return;const r=stage.getBoundingClientRect();const x=Math.max(-1,Math.min(1,(e.clientX-r.left)/r.width*2-1)),y=Math.max(-1,Math.min(1,(e.clientY-r.top)/r.height*2-1));if(raf)return;raf=requestAnimationFrame(()=>{raf=0;deck.style.setProperty('--rx',(-y*4).toFixed(2)+'deg');deck.style.setProperty('--ry',(x*6).toFixed(2)+'deg');});},{passive:true});
  hero.addEventListener('pointerleave',()=>{deck.style.setProperty('--rx','0deg');deck.style.setProperty('--ry','0deg');});}

/* ---------------- pane drawer on small screens ---------------- */
const pane=$('#pane'),scrim=$('#scrim');
const openPane=o=>{pane.classList.toggle('open',o);scrim.classList.toggle('open',o);};
$('#pane-btn').addEventListener('click',()=>openPane(true));$('#pane-x').addEventListener('click',()=>openPane(false));scrim.addEventListener('click',()=>openPane(false));
$('#icons').addEventListener('click',e=>{if(e.target.closest('a')&&innerWidth<=1100)openPane(false);});

/* deep link */
function goHash(){const id=decodeURIComponent(location.hash.slice(1));const el=id&&document.getElementById(id);if(el&&el.classList.contains('vis'))setTimeout(()=>{el.scrollIntoView({block:'start'});showBuild(id);},60);}
addEventListener('hashchange',goHash);goHash();
})();
