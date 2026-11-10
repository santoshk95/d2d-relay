/* ============================================================
   Brand engine: one brand color (or any pasted palette) becomes
   the full token set — chart colors, ramps, neutrals, accents —
   tuned separately for light and dark, injected as CSS.
   ============================================================ */
const BRAND=(()=>{
  const hex2rgb=h=>{h=String(h).trim().replace('#','');if(h.length===3)h=h.split('').map(c=>c+c).join('');const n=parseInt(h,16);return [(n>>16&255)/255,(n>>8&255)/255,(n&255)/255];};
  const lin=c=>c<=.04045?c/12.92:Math.pow((c+.055)/1.055,2.4);
  const gam=c=>c<=.0031308?12.92*c:1.055*Math.pow(Math.max(c,0),1/2.4)-.055;
  function rgb2lab(rgb){return labLin(rgb.map(lin));}
  function labLin([r,g,b]){
    const l=Math.cbrt(.4122214708*r+.5363325363*g+.0514459929*b),m=Math.cbrt(.2119034982*r+.6806995451*g+.1073969566*b),s=Math.cbrt(.0883024619*r+.2817188376*g+.6299787005*b);
    return [.2104542553*l+.793617785*m-.0040720468*s,1.9779984951*l-2.428592205*m+.4505937099*s,.0259040371*l+.7827717662*m-.808675766*s];}
  function lab2rgb([L,a,b]){const l=Math.pow(L+.3963377774*a+.2158037573*b,3),m=Math.pow(L-.1055613458*a-.0638541728*b,3),s=Math.pow(L-.0894841775*a-1.291485548*b,3);
    return [4.0767416621*l-3.3077115913*m+.2309699292*s,-1.2684380046*l+2.6097574011*m-.3413193965*s,-.0041960863*l-.7034186147*m+1.707614701*s];}
  const lch=hex=>{const [L,a,b]=rgb2lab(hex2rgb(hex));return [L,Math.hypot(a,b),(Math.atan2(b,a)*180/Math.PI+360)%360];};
  function hexOf(L,C,h){L=Math.max(0,Math.min(1,L));let c=Math.max(0,C),rl;
    for(let i=0;i<48;i++){const hr=h*Math.PI/180;rl=lab2rgb([L,c*Math.cos(hr),c*Math.sin(hr)]);if(rl.every(v=>v>=-.0004&&v<=1.0004))break;c*=.93;}
    return '#'+rl.map(v=>Math.round(Math.max(0,Math.min(1,gam(v)))*255).toString(16).padStart(2,'0')).join('');}
  const valid=h=>/^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.test(String(h).trim());
  const norm=h=>{h=String(h).trim();if(!h.startsWith('#'))h='#'+h;if(h.length===4)h='#'+h.slice(1).split('').map(c=>c+c).join('');return h.toLowerCase();};
  const lum=hex=>{const [r,g,b]=hex2rgb(hex).map(lin);return .2126*r+.7152*g+.0722*b;};
  const contrast=(a,b)=>{const x=lum(a),y=lum(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05);};
  const inkOn=hex=>contrast(hex,'#ffffff')>=contrast(hex,'#141414')*0.82?'#ffffff':'#141414';
  const mix=(a,b,t)=>{const A=rgb2lab(hex2rgb(a)),B=rgb2lab(hex2rgb(b));const rl=lab2rgb(A.map((v,i)=>v+(B[i]-v)*t));return '#'+rl.map(v=>Math.round(Math.max(0,Math.min(1,gam(v)))*255).toString(16).padStart(2,'0')).join('');};
  const rgba=(hex,a)=>{const [r,g,b]=hex2rgb(hex).map(v=>Math.round(v*255));return `rgba(${r},${g},${b},${a})`;};

  const PRESETS={
    atlas:['#2a78d6','#eb6834','#1baf7a','#eda100','#e87ba4','#008300','#6250d6','#e34948'],
    atlasDark:['#3987e5','#d95926','#199e70','#c98500','#d55181','#008300','#9085e9','#e66767'],
    classic:['#118dff','#12239e','#e66c37','#6b007b','#e044a7','#744ec2','#d9b300','#d64550']
  };
  const SEEDS=['#2a78d6','#0f766e','#7c3aed','#e11d48','#ea580c','#ca8a04','#16a34a','#334155'];

  const CVD=[[[.152286,1.052583,-.204868],[.114503,.786281,.099216],[-.003882,-.048116,1.051998]],[[.367322,.860646,-.227968],[.280085,.672501,.047413],[-.01182,.04294,.968881]]];
  const dE=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1],a[2]-b[2])*100;
  const LABC=new Map();
  function labs(hex){let v=LABC.get(hex);if(!v){const l=hex2rgb(hex).map(lin);v=[labLin(l),...CVD.map(M=>labLin(M.map(r=>Math.max(0,Math.min(1,r[0]*l[0]+r[1]*l[1]+r[2]*l[2])))))];LABC.set(hex,v);}return v;}
  function sep(a,b){const A=labs(a),B=labs(b);return {n:dE(A[0],B[0]),c:Math.min(dE(A[1],B[1]),dE(A[2],B[2]))};}
  /* greedy pick: each next color as far as possible from its neighbour (also for color-blind readers) and from all earlier colors */
  /* separation in both themes: the dark theme lifts dark colors, so check the adapted pair too */
  function sep2(a,b){const x=sep(adapt(a,false),adapt(b,false)),y=sep(adapt(a,true),adapt(b,true));return {n:Math.min(x.n,y.n),c:Math.min(x.c,y.c)};}
  function pick(first,pool,one){const S=one?sep:sep2,out=[first];
    while(out.length<8){let best=null,bs=-1;
      for(const p of pool){if(out.includes(p))continue;const a=S(out[out.length-1],p),b=out.length>1?S(out[out.length-2],p):{n:99,c:99};let all=1e9;for(const q of out)all=Math.min(all,S(q,p).n);
        const sc=Math.min(a.c*2.2,a.n,all*1.7,b.c*3.2);if(sc>bs){bs=sc;best=p;}}
      out.push(best);}
    return out;}
  /* data colors need chroma (>= .10 reads as a hue, not gray): keep the brand's hue, lift a muted brand, and start an achromatic brand from a calm blue */
  const lead=b=>{const [L,C,h]=lch(b);if(C<.03)return hexOf(.55,.13,250);if(C<.105){for(const l of [L,.55,.6,.65,.7,.5,.45].map(x=>Math.max(.45,Math.min(.72,x)))){const x=hexOf(l,.115,h);if(lch(x)[1]>=.1)return x;}return hexOf(.6,.115,h);}return b;};
  const chromaOK=a=>{const p=a.filter(x=>lch(x)[1]>=.1);return p.length>=20?p:a;};
  function generate(brand,mode){
    if(mode!=='mono'&&mode!=='monodark')brand=lead(brand);
    const [L,C,h]=lch(brand);const c=Math.max(.085,Math.min(.17,C<.03?.1:C));
    const out=[brand];
    if(mode==='analogous'){const pool=[];[0,30,-30,60,-60,90,-90].forEach(o=>[.46,.52,.58,.64,.7,.76].forEach(l=>pool.push(hexOf(l,Math.max(.12,c),(h+o+720)%360))));return pick(brand,chromaOK(pool));}
    else if(mode==='mono'){return pick(brand,[.26,.32,.38,.44,.5,.56,.62,.68,.74,.8,.85].filter(l=>Math.abs(l-L)>.045).map(l=>hexOf(l,(C<.03?.012:c)*(1-Math.abs(l-.62)*.7),h)),true);}
    else if(mode==='monodark'){const Ls=[.62,.9,.72,.5,.82,.58,.96,.42];return Ls.map(l=>hexOf(l,(C<.03?.012:c)*(1-Math.abs(l-.66)*.6),h));}
    else{const cs=Math.max(.12,c),all=[];for(let k=1;k<24;k++)for(const l of [.5,.56,.62,.68,.74])all.push(hexOf(l,cs,(h+k*15)%360));const pool=all.filter(x=>lch(x)[1]>=.1);return pick(brand,pool.length>=24?pool:all);}
    return out;
  }
  /* keep every color readable on the light and dark chart surfaces */
  /* keep categorical colors inside the validated lightness bands: light L .43–.77, dark L .48–.67 */
  function adapt(hex,dark){const [L,C,h]=lch(hex);
    if(dark){if(L<.48)return hexOf(Math.min(.62,Math.max(.52,L+.2)),C*1.04,h);if(L>.67)return hexOf(.65,C,h);return hex;}
    if(L>.77)return hexOf(.74,C<.03?C:Math.max(C,.06),h);if(L<.43)return hexOf(.45,C,h);return hex;}
  function ramp(hex,dark){const [,C,h]=lch(hex);const c=Math.max(.045,Math.min(.17,C));const Ls=[.955,.87,.77,.66,.55,.44,.33],Cs=[.22,.45,.7,.9,1,.92,.78];
    const a=Ls.map((l,i)=>hexOf(l,c*Cs[i],h));return dark?a.reverse():a;}

  const TOK=['c1','c2','c3','c4','c5','c6','c7','c8','s1','s2','s3','s4','s5','s6','s7','good','warn','crit','serious','muted-mark','track','dv1','dv2','dv3','dv4','dv5','dneg','dpos','dmid'];
  let state={brand:'#2a78d6',mode:'atlas',custom:'',look:'soft'};
  try{const s=JSON.parse(localStorage.getItem('atlas-brand')||'null');if(s&&valid(s.brand))state={...state,...s};}catch(e){}

  let PC={k:'',p:null};
  function palette(){const k=state.mode+'|'+state.brand+'|'+state.custom;if(PC.k!==k)PC={k,p:palette0()};return PC.p.slice();}
  function palette0(){
    if(state.mode==='atlas'||state.mode==='classic')return PRESETS[state.mode].slice();
    if(state.mode==='custom'){const list=(state.custom||'').split(/[\s,;]+/).filter(valid).map(norm);
      if(list.length){const out=list.slice(0,8);if(out.length<8){const gen=generate(out[0],'spectrum');for(let i=1;out.length<8;i++)out.push(gen[i]);}return out;}}
    return generate(norm(state.brand),state.mode);
  }
  function tokens(dark){
    const pal=themed(dark);
    const brand=state.mode==='atlas'||state.mode==='classic'?PRESETS[state.mode][0]:(state.mode==='custom'&&palette()[0])||norm(state.brand);
    const [bL,bC,bh]=lch(brand);const h=bh;const nc=Math.min(.012,bC*.08+.002);
    const T={};pal.forEach((c,i)=>{T['c'+(i+1)]=c;});
    ramp(pal[0],dark).forEach((c,i)=>{T['s'+(i+1)]=c;});
    T.dpos=pal[0];T.dneg=hexOf(dark?.66:.6,Math.max(.13,Math.min(.17,bC)),(h+180)%360);
    if(Math.abs(((h+180)%360)-lch(pal[0])[2])<25)T.dneg=dark?'#e66767':'#d64545';
    T.dmid=hexOf(dark?.34:.92,.006,h);
    T.dv1=T.dneg;T.dv2=mix(T.dneg,T.dmid,.52);T.dv3=T.dmid;T.dv4=mix(T.dpos,T.dmid,.52);T.dv5=T.dpos;
    Object.assign(T,{good:'#0ca30c',warn:'#fab219',crit:'#d03b3b',serious:'#ec835a'});
    if(dark){Object.assign(T,{canvas:hexOf(.155,nc,h),surface:hexOf(.198,nc,h),raised:hexOf(.24,nc*1.1,h),sunk:hexOf(.135,nc,h),ink:hexOf(.955,nc*.6,h),ink2:hexOf(.8,nc,h),muted:hexOf(.63,nc,h),grid:hexOf(.285,nc,h),base:hexOf(.4,nc,h),'muted-mark':hexOf(.38,nc,h),track:hexOf(.29,nc,h),land:hexOf(.29,nc,h),water:hexOf(.17,nc,h),mapline:hexOf(.198,nc,h)});}
    else{Object.assign(T,{canvas:hexOf(.968,nc*.7,h),surface:hexOf(.992,nc*.3,h),raised:'#ffffff',sunk:hexOf(.945,nc*.8,h),ink:hexOf(.19,nc,h),ink2:hexOf(.43,nc,h),muted:hexOf(.6,nc*.9,h),grid:hexOf(.905,nc*.7,h),base:hexOf(.79,nc,h),'muted-mark':hexOf(.85,nc,h),track:hexOf(.925,nc*.8,h),land:hexOf(.915,nc*.8,h),water:hexOf(.978,nc*.5,h),mapline:hexOf(.992,nc*.3,h)});}
    T.sh=dark?'#000000':hexOf(.27,Math.min(.045,bC*.3),h);
    T.accent=adapt(brand,dark);T['accent-ink']=inkOn(T.accent);
    T['accent-line']=dark?hexOf(Math.max(bL,.76),bC,h):hexOf(Math.min(bL,.5),bC,h);
    T['accent-soft']=rgba(T.accent,dark?.2:.14);T['accent-glow']=rgba(T.accent,dark?.38:.3);
    return T;
  }
  /* palette check: neighbouring colors under normal vision and protan/deutan simulation (Machado 2009, severity 1), OKLab ΔE × 100 */
  const themed=dark=>state.mode==='mono'&&dark?generate(norm(state.brand),'monodark'):state.mode==='atlas'&&dark?PRESETS.atlasDark.slice():state.mode==='custom'&&!dark?palette().map(c=>lch(c)[0]>.86?adapt(c,false):c):palette().map(c=>adapt(c,dark));
  function check(dark){const pal=themed(dark);let n=1e9,c=1e9;
    for(let i=0;i<pal.length-1;i++){const d=sep(pal[i],pal[i+1]);n=Math.min(n,d.n);c=Math.min(c,d.c);}
    return {n:Math.round(n),c:Math.round(c)};}
  function cssBlock(T){return Object.entries(T).map(([k,v])=>`--${k}:${v}`).join(';');}
  function inkRules(T,pre){return ['c1','c2','c3','c4','c5','c6','c7','c8','s1','s2','s3','s4','s5','s6','s7','good','warn','crit','serious','dv1','dv2','dv3','dv4','dv5','muted-mark','track'].map(k=>{const v=T[k]||'#888888';const ink=inkOn(/^#/.test(v)?v:'#888888');return `${pre} .v .ki-${k}{fill:${ink}}${pre} .hv .ki-${k}{color:${ink}}`;}).join('');}
  function apply(){
    const L=tokens(false),D=tokens(true);
    let css=`:root{${cssBlock(L)}}`+inkRules(L,':root');
    css+=`@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){${cssBlock(D)};color-scheme:dark}${inkRules(D,':root:not([data-theme="light"])')}}`;
    css+=`:root[data-theme="dark"]{${cssBlock(D)};color-scheme:dark}`+inkRules(D,':root[data-theme="dark"]');
    let el=document.getElementById('brand-css');if(!el){el=document.createElement('style');el.id='brand-css';(document.body||document.head).appendChild(el);}
    el.textContent=css;
    try{localStorage.setItem('atlas-brand',JSON.stringify(state));}catch(e){}
  }
  /* Power BI report theme: palette, structural colors, text sizes and the look as container styles.
     Built-in visuals take the container look (corners, shadow, border); the Atlas custom visuals also take the bar look. */
  const SCHEMA='https://raw.githubusercontent.com/microsoft/powerbi-desktop-samples/main/Report%20Theme%20JSON%20Schema/reportThemeSchema-2.159.json';
  /* every Atlas custom visual: keep in sync with the pbiviz.json files in visuals/ (tools/mk_themes.js reads them from there) */
  const ATLAS_VISUALS=['atlasColumns9A01238C3D0249F7B4F9DFBEA84D3599','atlasCompare1934AF42622F4D63BF12168C02806AC8','atlasDistribution1C4252B29C654CC1BF16155962622408','atlasFinance8C601CA9CAF44ADCB6574FA21FDDE583','atlasFlowBA37FC4A61814B33BF815C11D35148B1','atlasGauges797C4E4189814B78AD7FCCDFF53CBC47','atlasHierarchy21AE4CB2A0F74216862D09F0C9A3BF2E','atlasLines36E69B273DB443A5AF8E62CB16DB4547','atlasPartsA0676FD0579D44EFB545170E4799ADC9','atlasProportion74F95B1AE3CB4D9195CC248A3EC140A4','atlasScatter0B23674C661C4797A349BBC2B0AD313A','atlasTextC961F02E238E426A825D8355E3503AA9','atlasTime657C41A78B0A405A998ADA36387448E9'];
  function themeObject(look,dark){
    look=['flat','soft','3d'].includes(look)?look:(['flat','soft','3d'].includes(state.look)?state.look:'soft');dark=!!dark;
    const T=tokens(dark),pal=dark?themed(true):palette(),U=c=>String(c).toUpperCase(),F=c=>({solid:{color:U(c)}});
    const base=state.mode==='atlas'?'Relay':'Relay · '+(state.mode==='classic'?'Classic':state.mode==='custom'?'Custom brand':'Brand '+norm(state.brand).toUpperCase());
    const name=`${base} · ${look==='3d'?'3D':look==='soft'?'Soft':'Flat'}${dark?' · Dark':''}`;
    const surf=dark?T.surface:'#ffffff',radius={flat:4,soft:12,'3d':8}[look];
    const shadow=look==='flat'?{show:false}:{show:true,position:'Outer',preset:look==='3d'?'BottomRight':'Bottom',color:F(T.sh),
      transparency:dark?(look==='3d'?50:62):(look==='3d'?70:84),shadowBlur:look==='3d'?14:12,shadowDistance:look==='3d'?6:3,shadowSpread:0};
    const common={background:[{show:true,color:F(surf),transparency:0}],border:[{show:look==='flat',color:F(T.grid),radius,width:1}],dropShadow:[shadow],
      title:[{show:true,fontColor:F(T.ink),fontSize:12,bold:true}],padding:[{top:10,bottom:10,left:12,right:12}],
      valueAxis:[{gridlineStyle:look==='soft'?'dotted':'solid',gridlineColor:F(T.grid)}]};
    const vs={'*':{'*':common},page:{'*':{background:[{color:F(T.canvas),transparency:0}]}}};
    ATLAS_VISUALS.forEach(g=>{vs[g]={'*':{chart:[{look}],palette:[{source:'theme'}]}};});
    return {$schema:SCHEMA,name,dataColors:pal.map(U),foreground:U(T.ink),background:U(surf),tableAccent:U(pal[0]),
      good:'#1AAB40',neutral:'#D9B300',bad:'#D64554',maximum:U(T.s6),center:U(T.s3),minimum:U(T.s1),null:'#B3B0AD',
      firstLevelElements:U(T.ink),secondLevelElements:U(T.ink2),thirdLevelElements:U(T.grid),fourthLevelElements:U(T.muted),secondaryBackground:U(T.base),
      textClasses:{title:{fontSize:12,color:U(T.ink)},header:{fontSize:12,color:U(T.ink)},label:{fontSize:10,color:U(T.ink2)},callout:{fontSize:28,color:U(T.ink)}},
      visualStyles:vs};
  }
  function themeJSON(look,dark){return JSON.stringify(themeObject(look,dark),null,2);}
  return {get state(){return state;},set(p){state={...state,...p};apply();},apply,palette,tokens,themeJSON,themeObject,check,PRESETS,SEEDS,valid,norm,lch,hexOf,inkOn,TOK};
})();
