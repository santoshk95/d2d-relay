/* ============================================================
   Sample data model (deterministic; every number is invented)
   Three drillable hierarchies + datasets for specific visuals
   ============================================================ */
function rng(seed){let s=seed>>>0||1;return()=>{s^=s<<13;s>>>=0;s^=s>>>17;s^=s<<5;s>>>=0;return s/4294967296;};}
const MON=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
const SEAS=[.84,.8,.93,.96,1.01,1.04,.97,1,1.05,1.1,1.21,1.36];
const r100=v=>Math.round(v/100)*100;

function agg(n){
  if(n._a) return n._a;
  if(!n.c) return (n._a=n.v);
  const a=[];
  n.c.forEach(ch=>agg(ch).forEach((v,i)=>{a[i]=(a[i]||0)+v;}));
  return (n._a=a);
}

/* ---- Date hierarchy: Year > Quarter > Month  (v = [Sales, Profit, Units]) ---- */
const HD=(()=>{
  const r=rng(42);
  const root={n:'All',c:[2023,2024,2025].map((y,yi)=>({n:String(y),c:[0,1,2,3].map(q=>({n:'Qtr '+(q+1),c:[0,1,2].map(m=>{
    const mi=q*3+m;
    const s=r100(612000*Math.pow(1.12,yi)*SEAS[mi]*(.93+r()*.14));
    const p=r100(s*(.195+.022*Math.sin((mi+yi*3)/12*Math.PI*2)+(r()-.5)*.014));
    return {n:MON[mi],v:[s,p,Math.round(s/92),s-p]};
  })}))}))};
  return {root,levels:['Year','Quarter','Month'],ser:['Sales','Profit','Units']};
})();

/* ---- Product hierarchy: Category > Subcategory > Product ---- */
const HP=(()=>{
  const r=rng(7);
  const spec={
    Bikes:[['Road',.34],['Mountain',.3],['Touring',.16],['E-bike',.2]],
    Components:[['Wheels',.32],['Brakes',.24],['Drivetrain',.28],['Pedals',.16]],
    Clothing:[['Jerseys',.3],['Jackets',.32],['Gloves',.14],['Shorts',.24]],
    Accessories:[['Helmets',.36],['Lights',.24],['Locks',.22],['Bottles',.18]]
  };
  const share={Bikes:.55,Components:.2,Clothing:.14,Accessories:.11};
  const margin={Bikes:.12,Components:.2,Clothing:.31,Accessories:.38};
  const price={Bikes:1400,Components:160,Clothing:62,Accessories:28};
  const root={n:'All',c:Object.keys(spec).map(cat=>({n:cat,c:spec[cat].map(([sub,w])=>({n:sub,c:[1,2,3].map(k=>{
    const s=r100(8.9e6*share[cat]*w*[.46,.33,.21][k-1]*(.85+r()*.3));
    const p=r100(s*(margin[cat]+(r()-.5)*.09));
    return {n:sub+' '+(k*100),v:[s,p,Math.round(s/(price[cat]*(.7+k*.25)))]};
  })}))}))};
  return {root,levels:['Category','Subcategory','Product'],ser:['Sales','Profit','Units']};
})();

/* ---- Geography: Region > Country > City  (v = [Sales, Customers, Sales LY]) ---- */
const HG=(()=>{
  const r=rng(99);
  const spec={
    'Americas':{'United States':['New York','Chicago','San Francisco','Austin'],'Canada':['Toronto','Vancouver'],'Brazil':['São Paulo'],'Mexico':['Mexico City']},
    'Europe':{'United Kingdom':['London','Manchester'],'Germany':['Berlin','Munich'],'France':['Paris'],'Spain':['Madrid'],'Netherlands':['Amsterdam'],'Sweden':['Stockholm']},
    'Asia Pacific':{'Japan':['Tokyo','Osaka'],'Australia':['Sydney','Melbourne'],'India':['Mumbai','Bengaluru'],'Singapore':['Singapore'],'South Korea':['Seoul']},
    'Middle East & Africa':{'UAE':['Dubai'],'South Africa':['Johannesburg'],'Egypt':['Cairo'],'Nigeria':['Lagos'],'Kenya':['Nairobi']}
  };
  const big={'New York':2.2,'London':2,'Tokyo':1.9,'Chicago':1.3,'San Francisco':1.5,'Paris':1.4,'Berlin':1.1,'Sydney':1.1,'Toronto':1.1,'Mumbai':1,'Singapore':1,'Dubai':.9,'São Paulo':1};
  const root={n:'All',c:Object.entries(spec).map(([rg,cs])=>({n:rg,c:Object.entries(cs).map(([co,cities])=>({n:co,c:cities.map(ci=>{
    const s=r100(420000*(big[ci]||.6)*(.8+r()*.4));
    const ly=r100(s/(1+(r()*.3-.08)));
    return {n:ci,v:[s,Math.round(s/1150),ly]};
  })}))}))};
  return {root,levels:['Region','Country','City'],ser:['Sales','Customers','Sales LY']};
})();

/* ---- helpers to pull flat series out of the hierarchies ---- */
const leaves=n=>n.c?n.c.flatMap(leaves):[n];
const yearMonths=y=>leaves(HD.root.c.find(c=>c.n===String(y)));
const TY=yearMonths(2025).map(m=>m.v[0]);
const LY=yearMonths(2024).map(m=>m.v[0]);
const PY=yearMonths(2023).map(m=>m.v[0]);
const PROF=yearMonths(2025).map(m=>m.v[1]);
const UNITS=yearMonths(2025).map(m=>m.v[2]);
const M36=leaves(HD.root).map((m,i)=>m.n+(i%12===0?' '+(2023+i/12|0):''));
const S36=leaves(HD.root).map(m=>m.v[0]);
const TARGET=TY.map((v,i)=>r100((LY[i]*1.1+TY[i])/2.02));
const QTR=['Q1','Q2','Q3','Q4'];
const q=(arr)=>[0,1,2,3].map(k=>arr[k*3]+arr[k*3+1]+arr[k*3+2]);
const TYQ=q(TY), LYQ=q(LY);
const CAT4=HP.root.c.map(c=>c.n);
const CAT4S=HP.root.c.map(c=>agg(c)[0]);
const CAT4P=HP.root.c.map(c=>agg(c)[1]);
const SUBS=HP.root.c.flatMap(c=>c.c.map(s=>({n:s.n,cat:c.n,v:agg(s)})));
const PRODS=leaves(HP.root).map(p=>({n:p.n,v:p.v,cat:HP.root.c.find(c=>leaves(c).includes(p)).n}));
const TOPP=[...PRODS].sort((a,b)=>b.v[0]-a.v[0]).slice(0,8);
const REG4=HG.root.c.map(c=>c.n);
const REG4S=HG.root.c.map(c=>agg(c)[0]);
const CITIES=leaves(HG.root).map(c=>({n:c.n,v:c.v,reg:HG.root.c.find(r=>leaves(r).includes(c)).n}));

/* channel split per month (Online, Retail, Partner) */
const CH=['Online','Retail','Partner'];
const CHM=(()=>{const r=rng(3);const on=[],re=[],pa=[];TY.forEach((t,i)=>{const a=.36+i*.012+r()*.03,b=.42-i*.01+r()*.03;on.push(r100(t*a));re.push(r100(t*b));pa.push(r100(t*(1-a-b)));});return [on,re,pa];})();
const CHQ=CHM.map(q);
/* region x channel */
const REGCH=(()=>{const r=rng(8);return CH.map((c,ci)=>REG4S.map(s=>r100(s*[.44,.38,.18][ci]*(.8+r()*.4))));})();
/* region panels (quarterly TY/LY) for small multiples */
const REGQ=(()=>{const r=rng(12);return REG4.map((n,ri)=>({n,ty:TYQ.map(v=>r100(v*REG4S[ri]/sum0(REG4S)*(.85+r()*.3))),ly:LYQ.map(v=>r100(v*REG4S[ri]/sum0(REG4S)*(.85+r()*.3)))}));})();
function sum0(a){return a.reduce((s,v)=>s+(v||0),0);}

/* survey (Likert) for 100% stacked bars */
const LIK={cats:['Easy to find products','Checkout was quick','Delivery arrived on time','Support solved my issue','Would recommend us'],
  lv:['Strongly disagree','Disagree','Neutral','Agree','Strongly agree'],
  v:[[4,7,6,12,9],[9,12,10,19,14],[17,21,22,24,20],[44,38,40,30,35],[26,22,22,15,22]]};

/* traffic source share by month */
const TRAF=(()=>{const r=rng(21);const n=['Organic search','Paid search','Social','Email','Direct'];const base=[38,22,14,9,17];
  return {n,v:n.map((_,k)=>MON.map((m,i)=>Math.max(2,Math.round(base[k]+(k===2?i*.9:k===0?-i*.5:0)+(r()-.5)*4))))};})();

/* ribbon: brand rank changes by quarter */
const RIB={cats:['Q1 24','Q2 24','Q3 24','Q4 24','Q1 25','Q2 25','Q3 25','Q4 25'],n:['Road','Mountain','E-bike','Touring','Kids'],
  v:[[410,430,420,470,450,440,430,460],[380,400,440,450,430,450,470,480],[180,240,300,360,420,490,540,610],[300,280,270,260,250,240,230,220],[150,160,190,240,170,180,210,260]]};

/* waterfalls */
const WF_BRIDGE=[{n:'2024 revenue',t:'total',v:7680000},{n:'New customers',v:1210000},{n:'Upsell',v:640000},{n:'Price change',v:320000},{n:'Churn',v:-710000},{n:'Discounts',v:-380000},{n:'Currency',v:-120000},{n:'2025 revenue',t:'total'}];
const WF_PNL=[{n:'Revenue',t:'total',v:8640000},{n:'Cost of goods',v:-4920000},{n:'Gross profit',t:'total'},{n:'Marketing',v:-860000},{n:'Admin',v:-740000},{n:'R&D',v:-480000},{n:'Operating profit',t:'total'}];
const WF_BRK=[{n:'2024',t:'total',v:7680000},{n:'Bikes',v:620000},{n:'Components',v:180000},{n:'Clothing',v:-90000},{n:'Accessories',v:110000},{n:'Services',v:-40000},{n:'2025',t:'total'}];
const WF_CASH=(()=>{const r=rng(4);const out=[{n:'Opening',t:'total',v:2400000}];MON.forEach((m,i)=>out.push({n:m,v:r100((r()-.38)*620000)}));out.push({n:'Closing',t:'total'});return out;})();

/* funnel */
const PIPE=[{n:'Leads',v:48200},{n:'Qualified',v:21400},{n:'Proposal',v:9800},{n:'Negotiation',v:4300},{n:'Closed won',v:1780}];

/* stores for scatter (3 formats: within the 3-slot cap for scatter colors) */
const STORES=(()=>{const r=rng(31);const out=[];const fm=['Flagship','Mall','Outlet'];
  for(let i=0;i<36;i++){const g=i%3;const spend=Math.round((g===0?60:g===1?34:18)+r()*(g===0?40:28));const rev=Math.round(spend*(g===2?9.5:g===1?8:7)*(.75+r()*.5)+40*r());
    out.push({n:fm[g]+' '+String.fromCharCode(65+(i/3|0)),x:spend,y:rev,s:Math.round(rev*(1.2+r())),g});}
  return out;})();
/* play axis frames: 8 markets, 5 years */
const PLAY=(()=>{const r=rng(17);const mk=['US','UK','Germany','Japan','Australia','India','Brazil','UAE'];const yrs=['2021','2022','2023','2024','2025'];
  const st=mk.map(()=>({x:2+r()*6,y:8+r()*12,s:200+r()*900,dx:(r()-.3)*3,dy:(r()-.45)*3,ds:60+r()*180}));
  return {yrs,mk,frames:yrs.map((y,yi)=>mk.map((m,i)=>({n:m,x:Math.round((st[i].x+st[i].dx*yi+(r()-.5))*10)/10,y:Math.round((st[i].y+st[i].dy*yi+(r()-.5)*1.5)*10)/10,s:Math.round(st[i].s+st[i].ds*yi)})))};})();
/* plan vs actual by department */
const PVA=(()=>{const r=rng(29);return ['Sales','Marketing','Support','Finance','HR','Engineering','Logistics','Legal','IT','Facilities','Product','Research'].map(d=>{const p=Math.round(120+r()*780);return {n:d,x:p,y:Math.round(p*(.78+r()*.42)),g:0};});})();
/* delivery days by carrier (dot plot) */
const DOTS=(()=>{const r=rng(55);const c=['Air','Express','Ground','Freight'];const out=[];c.forEach((n,ci)=>{for(let k=0;k<14;k++)out.push({c:ci,y:Math.round(([1.4,2.6,4.8,7.5][ci]+(r()-.5)*[1,1.6,2.4,4][ci])*10)/10,n:n+' #'+(k+1)});});return {cats:c,pts:out};})();
/* product scatter (price vs margin; log x) */
const PRODPTS=PRODS.map(p=>({n:p.n,x:Math.round(p.v[0]/p.v[2]),y:Math.round(p.v[1]/p.v[0]*1000)/10,s:p.v[0],g:Math.min(2,CAT4.indexOf(p.cat)),cat:p.cat}));

/* Gantt project (days from Mon 6 Jan 2025) */
const GANTT_D0=new Date(2025,0,6);
const GANTT=[
  {g:'Planning',n:'Kickoff',s:0,e:null,p:1,o:'AK'},
  {g:'Planning',n:'Requirements',s:0,e:12,p:1,o:'AK'},
  {g:'Planning',n:'Budget approval',s:9,e:16,p:1,o:'MR'},
  {g:'Design',n:'UX research',s:12,e:26,p:1,o:'JS'},
  {g:'Design',n:'Visual design',s:21,e:40,p:.85,o:'JS'},
  {g:'Design',n:'Design sign-off',s:40,e:null,p:0,o:'MR'},
  {g:'Build',n:'Data model',s:28,e:52,p:.7,o:'DL'},
  {g:'Build',n:'Report pages',s:38,e:68,p:.45,o:'PN'},
  {g:'Build',n:'Row-level security',s:55,e:70,p:.2,o:'DL'},
  {g:'Test',n:'UAT',s:66,e:84,p:0,o:'TW'},
  {g:'Test',n:'Performance tuning',s:74,e:88,p:0,o:'DL'},
  {g:'Launch',n:'Go-live',s:91,e:null,p:0,o:'AK'},
  {g:'Launch',n:'Training',s:86,e:100,p:0,o:'TW'}
];

/* US states: population (millions) and census region */
const USPOP={AL:5.1,AK:.73,AZ:7.4,AR:3.1,CA:39,CO:5.9,CT:3.6,DE:1,DC:.68,FL:22.6,GA:11,HI:1.4,ID:1.96,IL:12.5,IN:6.9,IA:3.2,KS:2.9,KY:4.5,LA:4.6,ME:1.4,MD:6.2,MA:7,MI:10,MN:5.7,MS:2.9,MO:6.2,MT:1.1,NE:2,NV:3.2,NH:1.4,NJ:9.3,NM:2.1,NY:19.6,NC:10.8,ND:.78,OH:11.8,OK:4.05,OR:4.2,PA:13,RI:1.1,SC:5.4,SD:.92,TN:7.1,TX:30.5,UT:3.4,VT:.65,VA:8.7,WA:7.8,WV:1.77,WI:5.9,WY:.58};
const USREG={Northeast:'CT ME MA NH RI VT NJ NY PA',Midwest:'IL IN MI OH WI IA KS MN MO NE ND SD',South:'DE FL GA MD NC SC VA DC WV AL KY MS TN AR LA OK TX',West:'AZ CO ID MT NV NM UT WY AK CA HI OR WA'};
const US=(()=>{const r=rng(5);const reg={};Object.entries(USREG).forEach(([k,v])=>v.split(' ').forEach(a=>reg[a]=k));
  const o={};Object.entries(USPOP).forEach(([a,p])=>{o[a]={s:r100(p*61000*(.72+r()*.56)),g:Math.round((r()*.28-.1)*1000)/10,r:reg[a]};});return o;})();
const USCITYV=(()=>{const r=rng(77);const o={};Object.keys(GEO.us.cities).forEach(c=>{o[c]=r100(180000+r()*900000);});o['New York']=1450000;o['Los Angeles']=1210000;o['Chicago']=980000;return o;})();
/* hex tile layout (row, col) */
const HEX={AK:[0,0],ME:[0,11],WI:[1,6],VT:[1,10],NH:[1,11],WA:[2,1],ID:[2,2],MT:[2,3],ND:[2,4],MN:[2,5],IL:[2,6],MI:[2,7],NY:[2,9],MA:[2,10],
  OR:[3,1],NV:[3,2],WY:[3,3],SD:[3,4],IA:[3,5],IN:[3,6],OH:[3,7],PA:[3,8],NJ:[3,9],CT:[3,10],RI:[3,11],
  CA:[4,1],UT:[4,2],CO:[4,3],NE:[4,4],MO:[4,5],KY:[4,6],WV:[4,7],VA:[4,8],MD:[4,9],DE:[4,10],
  AZ:[5,2],NM:[5,3],KS:[5,4],AR:[5,5],TN:[5,6],NC:[5,7],SC:[5,8],DC:[5,9],OK:[6,4],LA:[6,5],MS:[6,6],AL:[6,7],GA:[6,8],HI:[7,0],TX:[7,4],FL:[7,9]};

/* table rows */
const TROWS=TOPP.map((p,i)=>{const r=rng(100+i);const tr=MON.map((m,k)=>Math.round(p.v[0]/12*(SEAS[k]*(.85+r()*.3))));const yoy=Math.round((r()*.4-.12)*1000)/10;
  return {n:p.n,cat:p.cat,s:p.v[0],u:p.v[2],m:Math.round(p.v[1]/p.v[0]*1000)/10,y:yoy,tr};});

/* matrix: region > country by quarter (2025) */
const MAT=HG.root.c.map(rg=>({n:rg.n,c:rg.c.map(co=>{const t=agg(co)[0];const r=rng(co.n.length*13);const sp=[.22,.24,.25,.29].map(f=>f*(.9+r()*.2));const k=sum0(sp);return {n:co.n,q:sp.map(f=>r100(t*f/k))};})}));

/* key influencers (churn) */
const KI={target:'Churn',val:'Yes',base:14.2,
  f:[{n:'Support tickets is more than 5',x:2.4,p:34.1,pop:612},{n:'Contract is Monthly',x:1.9,p:27,pop:2140},{n:'Tenure is less than 6 months',x:1.7,p:24.1,pop:930},{n:'Region is West',x:1.3,p:18.5,pop:1480},{n:'Plan is Basic',x:1.2,p:17,pop:2610}],
  seg:[{n:'Monthly contract, tenure < 6 months',p:41,pop:410},{n:'Support tickets > 5, Basic plan',p:36,pop:280},{n:'West, Monthly contract',p:29,pop:640},{n:'Annual contract, 2+ add-ons',p:4,pop:1210}]};
