/* ============================================================
   Looks: Flat, Soft (gradients, shadows, glow) and 3D (adds
   extruded bars, tilted pies, raised maps). Gradients live in one
   hidden SVG; their stops read CSS variables, so a brand change
   recolors every chart without re-rendering.
   ============================================================ */
const LOOK=(()=>{
  const T=['c1','c2','c3','c4','c5','c6','c7','c8','s1','s2','s3','s4','s5','s6','s7','good','warn','crit','serious','muted-mark','track','dv1','dv2','dv3','dv4','dv5','dneg','dpos','accent','ink'];
  const mixW=(t,p)=>`color-mix(in oklab,var(--${t}) ${p}%,#fff)`,mixB=(t,p)=>`color-mix(in oklab,var(--${t}) ${p}%,#000)`;
  function defs(){
    let g='';
    T.forEach(t=>{
      const st=`<stop offset="0" style="stop-color:${mixW(t,58)}"/><stop offset=".55" style="stop-color:var(--${t})"/><stop offset="1" style="stop-color:${mixB(t,80)}"/>`;
      g+=`<linearGradient id="lg-${t}" x1="0" y1="0" x2="0" y2="1">${st}</linearGradient>`;
      g+=`<linearGradient id="lh-${t}" x1="1" y1="0" x2="0" y2="0">${st}</linearGradient>`;
      g+=`<radialGradient id="rg-${t}" cx=".38" cy=".32" r=".78" fx=".3" fy=".22"><stop offset="0" style="stop-color:${mixW(t,28)}"/><stop offset=".5" style="stop-color:var(--${t})"/><stop offset="1" style="stop-color:${mixB(t,62)}"/></radialGradient>`;
      g+=`<linearGradient id="la-${t}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" style="stop-color:var(--${t});stop-opacity:.55"/><stop offset=".7" style="stop-color:var(--${t});stop-opacity:.12"/><stop offset="1" style="stop-color:var(--${t});stop-opacity:.02"/></linearGradient>`;
    });
    g+=`<filter id="f-sh" x="-10%" y="-12%" width="120%" height="140%" color-interpolation-filters="sRGB"><feDropShadow dx="0" dy="2.4" stdDeviation="2.4" style="flood-color:var(--sh);flood-opacity:var(--sho)"/></filter>`;
    g+=`<filter id="f-sh3" x="-12%" y="-15%" width="130%" height="150%" color-interpolation-filters="sRGB"><feDropShadow dx="2.5" dy="5" stdDeviation="3.6" style="flood-color:var(--sh);flood-opacity:var(--sho3)"/></filter>`;
    g+=`<filter id="f-glow" x="-10%" y="-40%" width="120%" height="200%" color-interpolation-filters="sRGB"><feGaussianBlur in="SourceGraphic" stdDeviation="2.8" result="b"/><feOffset in="b" dy="4" result="o"/><feComponentTransfer in="o" result="t"><feFuncA type="linear" slope=".42"/></feComponentTransfer><feMerge><feMergeNode in="t"/><feMergeNode in="SourceGraphic"/></feMerge></filter>`;
    g+=`<filter id="f-land" x="-5%" y="-5%" width="110%" height="120%" color-interpolation-filters="sRGB"><feDropShadow dx="0" dy="3" stdDeviation="2.2" style="flood-color:var(--sh);flood-opacity:var(--sho3)"/></filter>`;
    g+=`<radialGradient id="sheen" cx=".36" cy=".26" r=".9"><stop offset="0" stop-color="#fff" stop-opacity=".46"/><stop offset=".45" stop-color="#fff" stop-opacity=".08"/><stop offset="1" stop-color="#000" stop-opacity=".16"/></radialGradient>`;
    g+=`<linearGradient id="gloss" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".34"/><stop offset=".5" stop-color="#fff" stop-opacity="0"/></linearGradient>`;
    const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
    svg.setAttribute('aria-hidden','true');svg.setAttribute('width','0');svg.setAttribute('height','0');
    svg.style.cssText='position:absolute;width:0;height:0;overflow:hidden';
    svg.innerHTML=`<defs>${g}</defs>`;document.body.prepend(svg);
  }
  function css(){
    const R=':root:is([data-look="soft"],[data-look="3d"])';let s='';
    T.forEach(t=>{
      s+=`${R} .v :is(.m:not(.pr):not(.mh),.fr:not(.frh),.gf).k-${t}{fill:url(#lg-${t})!important}`;
      s+=`${R} .v :is(.m.mh:not(.pr),.frh).k-${t}{fill:url(#lh-${t})!important}`;
      s+=`${R} .v :is(.dot,.bub,.sph).k-${t}{fill:url(#rg-${t})!important}`;
      s+=`${R} .v .ar.k-${t}{fill:url(#la-${t})!important;fill-opacity:1!important}`;
      s+=`${R} .v .ars.k-${t}{fill:url(#lg-${t})!important;fill-opacity:.9!important}`;
      s+=`${R} .v .rbn.k-${t}{fill:url(#lg-${t})!important}`;
      s+=`.v .pz.sd.k-${t}{fill:${mixB(t,64)}}.v .pz.tp.k-${t}{fill:${mixW(t,62)}}.v .pz.wl.k-${t}{fill:${mixB(t,70)}}`;
    });
    const el=document.createElement('style');el.id='look-css';el.textContent=s;(document.body||document.head).appendChild(el);
  }
  let ready=false;
  return {
    init(){if(ready)return;ready=true;defs();css();},
    set(name){document.documentElement.setAttribute('data-look',name);E.look=name;}
  };
})();
