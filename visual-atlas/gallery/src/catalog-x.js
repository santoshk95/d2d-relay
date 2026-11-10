/* ============================================================
   Extended catalog: visuals from AppSource and build-your-own
   techniques (Deneb, SVG and HTML measures). Sample data is
   derived from the same invented bike retailer as the rest.
   ============================================================ */
const xNorm=r=>{let u=0,v=0;while(!u)u=r();while(!v)v=r();return Math.sqrt(-2*Math.log(u))*Math.cos(2*Math.PI*v);};
const GMV=q=>`Visualizations pane › … › Get more visuals › search “${q}” · Add`;

/* ---- data ---- */
const X_SK={u:'',vn:'Sessions',nodes:[{n:'Organic search',col:0,c:1},{n:'Paid search',col:0,c:2},{n:'Social',col:0,c:3},{n:'Email',col:0,c:4},{n:'Direct',col:0,c:5},
  {n:'Product page',col:1,c:6},{n:'Category page',col:1,c:7},{n:'Home page',col:1,c:8},{n:'Purchase',col:2,c:'dpos'},{n:'Sign-up',col:2,c:'dv4'},{n:'Bounce',col:2,c:'muted-mark'}],
  links:[[0,5,1900],[0,6,1500],[0,7,800],[1,5,1600],[1,6,600],[1,7,400],[2,5,500],[2,6,700],[2,7,600],[3,5,700],[3,6,300],[3,7,200],[4,5,600],[4,6,500],[4,7,1100],
    [5,8,1700],[5,9,900],[5,10,2700],[6,8,700],[6,9,800],[6,10,2100],[7,8,300],[7,9,700],[7,10,2100]].map(([s,t,v])=>({s,t,v}))};
const X_PNL=(()=>{const rev=sumA(CAT4S),cogs=r100(rev*.57),gp=rev-cogs,mk=r100(rev*.1),ad=r100(rev*.085),rd=r100(rev*.055),op=gp-mk-ad-rd;
  return {u:'$',vn:'Amount',linkBy:'target',nodes:[...CAT4.map((n,i)=>({n,col:0,c:i+1})),{n:'Revenue',col:1,c:'s6'},{n:'Cost of goods',col:2,c:'dneg'},{n:'Gross profit',col:2,c:'dpos'},{n:'Marketing',col:3,c:'dneg'},{n:'Admin',col:3,c:'dneg'},{n:'R&D',col:3,c:'dneg'},{n:'Operating profit',col:3,c:'dpos'}],
    links:[...CAT4S.map((v,i)=>({s:i,t:4,v,c:i+1})),{s:4,t:5,v:cogs},{s:4,t:6,v:gp},{s:6,t:7,v:mk},{s:6,t:8,v:ad},{s:6,t:9,v:rd},{s:6,t:10,v:op}]};})();
const X_SK2={u:'',vn:'Sessions',nodes:X_SK.nodes,links:X_SK.links};
const X_BRANDS=['Velo (us)','Apex','Cadence','Ridgeline','Summit'];
const X_SWITCH=[[0,42,31,18,12],[58,0,22,15,9],[36,19,0,24,11],[21,14,27,0,16],[15,8,10,13,0]].map(r=>r.map(v=>v*100));
const X_TRADE={names:['North America','Europe','Asia','Latin America','Africa'],m:[[0,320,410,180,40],[290,0,380,90,120],[520,460,0,140,110],[160,70,120,0,20],[30,140,90,15,0]].map(r=>r.map(v=>v*1e6))};
const X_ORG=[{n:'Maya Okafor',t:'Chief Executive Officer',ts:'CEO',p:null,c:'s6'},
  {n:'Liam Chen',t:'Chief Operating Officer',ts:'Operations',p:0,c:1,hc:214},{n:'Sofia Rossi',t:'Chief Financial Officer',ts:'Finance',p:0,c:2,hc:38},{n:'Arjun Mehta',t:'Chief Technology Officer',ts:'Technology',p:0,c:3,hc:61},{n:'Emma Larsen',t:'Chief Marketing Officer',ts:'Marketing',p:0,c:4,hc:27},
  {n:'Noah Kim',t:'Head of Operations',ts:'Operations',p:1},{n:'Ava Müller',t:'Supply Chain Lead',ts:'Supply chain',p:1},{n:'Lucas Silva',t:'Store Network Lead',ts:'Stores',p:1},
  {n:'Isla Grant',t:'Financial Controller',ts:'Controller',p:2},{n:'Omar Haddad',t:'FP&A Lead',ts:'FP&A',p:2},
  {n:'Zoe Martin',t:'Engineering Manager',ts:'Engineering',p:3},{n:'Ethan Park',t:'Data & BI Lead',ts:'Data & BI',p:3},{n:'Nina Ivanova',t:'Security Lead',ts:'Security',p:3},
  {n:'Leo Dubois',t:'Brand Lead',ts:'Brand',p:4},{n:'Mia Santos',t:'Growth Lead',ts:'Growth',p:4}];
const X_ORD=(()=>{const r=rng(31),on=[],re=[];for(let k=0;k<520;k++)on.push(Math.round(Math.exp(5.75+.5*xNorm(r))));for(let k=0;k<380;k++)re.push(Math.round(Math.exp(6.15+.42*xNorm(r))));return {on,re};})();
const X_DEL=['Air','Express','Ground','Freight'].map((n,i)=>{const r=rng(70+i),m=[1.6,2.8,4.9,7.4][i],s=[.45,.8,1.3,2.1][i];return {n,v:[...Array(60)].map(()=>Math.max(.5,Math.round((m+s*xNorm(r)+(r()<.05?s*3.2:0))*10)/10))};});
const X_SESS=(()=>{const spec=[['Desktop',[[6.5,2,1]]],['Mobile',[[3.2,1.3,1]]],['Tablet',[[5,1.7,1]]],['App',[[2,.8,.5],[8.2,1.5,.5]]]];return spec.map(([n,mix],i)=>{const r=rng(140+i),v=[];for(let k=0;k<160;k++){let u=r(),c=mix[0];for(const m of mix){if(u<m[2]){c=m;break;}u-=m[2];}v.push(Math.max(.3,Math.round((c[0]+c[1]*xNorm(r))*10)/10));}return {n,v};});})();
const X_BUL=[{n:'Revenue',sub:'$, year to date',v:TYS,t:r100(TYS*1.05),b:[TYS*.75,TYS*.92],max:TYS*1.2,u:'$'},{n:'Gross margin',sub:'percent',v:42.8,t:45,b:[36,41],max:50,u:'%'},{n:'New customers',sub:'count',v:5240,t:5000,b:[3800,4600],max:6000,u:''},
  {n:'Satisfaction',sub:'score of 100',v:81,t:85,b:[70,78],max:100,u:''},{n:'On-time delivery',sub:'percent',v:94.2,t:95,b:[88,92],max:100,u:'%'}];
const X_PAR={groups:CAT4,dims:[{n:'Sales',u:'$'},{n:'Profit',u:'$'},{n:'Units',u:''},{n:'Margin',u:'%'},{n:'Avg price',u:'$'}],rows:SUBS.map(s=>({n:s.n,g:CAT4.indexOf(s.cat),v:[s.v[0],s.v[1],s.v[2],Math.round(s.v[1]/s.v[0]*1000)/10,Math.round(s.v[0]/s.v[2])]}))};
const X_CTRY=HG.root.c.flatMap(r=>r.c.map(c=>({n:c.n,a:agg(c)[2],b:agg(c)[0]}))).sort((a,b)=>b.b-a.b).slice(0,10);
const X_PR=HP.root.c.flatMap(c=>c.c.map(s=>{const ps=leaves(s).map(p=>p.v[0]/p.v[2]);return {n:s.n,lo:Math.round(Math.min(...ps)),hi:Math.round(Math.max(...ps)),mid:Math.round(sumA(ps)/ps.length)};})).sort((a,b)=>b.hi-a.hi).slice(0,9);
const X_REGY=HG.root.c.map(r=>({n:r.n,a:agg(r)[2],b:agg(r)[0]}));
const X_MARG=[['Road',11.2,12.8],['Mountain',10.4,9.1],['E-bike',8.6,13.9],['Touring',9.8,9.5],['Wheels',14.1,13.2],['Jackets',18.3,17.6],['Helmets',21.5,20.2],['Lights',24.8,22.9]].map(([n,a,b])=>({n,a,b}));
const X_BUMP=(()=>{const names=['Road','Mountain','E-bike','Touring','Wheels','Drivetrain'],r=rng(88),per=['Q1 24','Q2 24','Q3 24','Q4 24','Q1 25','Q2 25','Q3 25','Q4 25'];let v=[1633,1397,961,777,520,537].map(x=>x*250);const V=names.map(()=>[]);
  per.forEach(()=>{v=v.map((x,i)=>x*(1+(i===2?.13:i===1?-.035:i===5?.03:0)+(r()-.5)*.12));v.forEach((x,i)=>V[i].push(r100(x)));});const R=names.map(()=>[]);per.forEach((_,k)=>{names.map((_,i)=>i).sort((a,b)=>V[b][k]-V[a][k]).forEach((i,rk)=>{R[i][k]=rk+1;});});
  return {periods:per,series:names.map((n,i)=>({n,r:R[i],v:V[i]}))};})();
const X_AGE={cats:['16–24','25–34','35–44','45–54','55–64','65+'],l:[3100,6800,7400,5900,3800,2100],r:[4200,8900,9600,7100,4400,2600]};
const X_SENS={base:1660000,rows:[{n:'Unit price',ll:'−5%',hl:'+5%',lo:1220000,hi:2100000},{n:'Sales volume',ll:'−10%',hl:'+10%',lo:1280000,hi:2040000},{n:'Cost of goods',ll:'+3%',hl:'−3%',lo:1510000,hi:1810000},{n:'Currency (EUR)',ll:'−8%',hl:'+8%',lo:1470000,hi:1850000},{n:'Marketing spend',ll:'+10%',hl:'−10%',lo:1570000,hi:1750000},{n:'Churn',ll:'+2 pt',hl:'−2 pt',lo:1530000,hi:1740000}]};
const X_RAX=['Price','Quality','Delivery','Support','Range','Brand'];
const X_RAD=[{n:'Our bikes',v:[7,9,6,8,7,8]},{n:'Market leader',v:[8,7,8,5,6,9]}];
const X_RADM=[[7,9,6,8,7,8],[8,8,7,6,9,6],[6,7,8,7,5,7],[9,6,7,8,8,5]].map((v,i)=>({n:CAT4[i],series:[{n:CAT4[i],v,c:i+1}]}));
const X_WORDS=[['fast delivery',96,.8,0],['helpful staff',82,.9,0],['price',78,-.2,2],['quality',74,.7,1],['returns',61,-.6,0],['sizing',55,-.4,1],['e-bike range',52,.5,1],['checkout',47,-.3,3],['packaging',41,.3,0],['out of stock',39,-.7,1],['app',35,.1,3],['warranty',31,.4,1],['assembly',29,-.5,1],['colors',26,.6,1],['support chat',24,-.1,3],['loyalty points',22,.5,2],['delivery slots',20,-.4,0],['test ride',18,.8,0],['brakes',16,-.2,1],['gift cards',14,.3,2],['site speed',13,-.5,3],['click & collect',12,.6,0],['tracking',11,.2,3],['discounts',10,.4,2],['service plan',9,.3,2],['frame size',9,-.3,1]].map(([t,v,s,g])=>({t,v,s,g}));
const X_DAYS=(()=>{const r=rng(17);return [...Array(365)].map((_,k)=>{const d=xDate(k),dow=(d.getUTCDay()+6)%7,m=d.getUTCMonth(),dd=d.getUTCDate();const seas=1+.35*Math.sin((k-80)/365*2*Math.PI);let v=120*seas*[1.05,1,1,1.02,1.12,1.32,1.18][dow]*(.82+r()*.36);if(m===10&&dd>=28)v*=2.3;if(m===11&&dd>=24&&dd<=26)v*=.25;return Math.round(v);});})();
const X_HRS=[...Array(18)].map((_,j)=>j+6),X_HRL=X_HRS.map(h=>h<12?h+'a':h===12?'12p':(h-12)+'p');
const X_HG=(()=>{const r=rng(23);return XDN.map((d,i)=>X_HRS.map(h=>{const we=i>=5;const pk=we?Math.exp(-((h-13)**2)/18):Math.exp(-((h-12.5)**2)/6)*.7+Math.exp(-((h-19.5)**2)/5);return Math.round((we?95:70)*pk*(.85+r()*.3)+4);}));})();
const X_M24=[...MON.map((m,i)=>i?m:'Jan 24'),...MON.map((m,i)=>i?m:'Jan 25')];
const X_STREAM=(()=>{const r=rng(29),subs=SUBS.slice().sort((a,b)=>b.v[0]-a.v[0]).slice(0,7);return {cats:X_M24,series:subs.map((s,i)=>({n:s.n,v:X_M24.map((_,k)=>r100(s.v[0]/12*(1+.38*Math.sin((k%12-2-i*.6)/12*2*Math.PI))*(1+(s.n==='E-bike'?.03:i===1?-.006:.004)*k)*(.9+r()*.2)))}))};})();
const X_OHLC=(()=>{const r=rng(91);let p=42;const out=[];let d=Date.UTC(2025,5,2);while(out.length<120){const dt=new Date(d);const dow=dt.getUTCDay();d+=864e5;if(dow===0||dow===6)continue;const o=p,ch=(r()-.47)*1.5+(out.length>70?.1:0),c=Math.max(5,o+ch),h=Math.max(o,c)+r()*.8,l=Math.min(o,c)-r()*.8;
  out.push({d:MON[dt.getUTCMonth()]+' '+dt.getUTCDate(),o:+o.toFixed(2),h:+h.toFixed(2),l:+l.toFixed(2),c:+c.toFixed(2),v:Math.round(8e5+r()*1.2e6+Math.abs(ch)*6e5)});p=c;}return out;})();
const X_TL=yearMonths(2024).map(m=>m.v[0]).concat(TY);
const X_TICK=[{l:'Sales',v:fmt(TYS,'$'),d:pctCh(TYS,LYS),tr:TY},{l:'Orders',v:fmt(ORD),d:pctCh(ORD,ORDL),tr:UNITS},{l:'Profit',v:fmt(PRS,'$'),d:pctCh(PRS,PRLS),tr:PROF},{l:'Return rate',v:'2.8%',d:-9.7,inv:true},{l:'NPS',v:'61',d:4.2},{l:'Avg order',v:'$214',d:3.3},{l:'E-bike sales',v:'$961K',d:31.2},{l:'Stock cover',v:'38 days',d:-2.4,inv:true}];
const X_FEED=[['09:42','Order #48211 · Road 200 · $2,140'],['09:41','Return approved · Gloves M · $38'],['09:39','Order #48210 · E-bike City · $3,480'],['09:37','Store check-in · Chicago · 14 visitors'],['09:36','Order #48209 · Helmet Pro · $129'],['09:34','Service booked · Utrecht · Tune-up'],['09:31','Order #48208 · Wheels set · $640'],['09:30','Stock alert · Lights 400 · 6 left']].map(([t,x])=>({t,x}));
const X_SVT=(()=>{const r=rng(303);return TOPP.slice(0,6).map(p=>({n:p.n,v:p.v[0],t:r100(p.v[0]*[.9,1.12,.97,1.04,.86,1.21][TOPP.indexOf(p)]),m:Math.round(p.v[1]/p.v[0]*1000)/10,tr:TY.map(v=>v*(.85+r()*.3))}));})();

/* ---- Deneb specifications (Vega-Lite) ---- */
const X_SPEC_RIDGE=`{
  "data": {"name": "dataset"},
  "transform": [{
    "density": "Orders",
    "groupby": ["Month"],
    "extent": [40, 380]
  }],
  "facet": {"row": {"field": "Month", "header": null}},
  "spacing": -18,
  "spec": {
    "height": 26,
    "mark": {"type": "area", "fillOpacity": 0.85},
    "encoding": {
      "x": {"field": "value", "type": "quantitative"},
      "y": {"field": "density", "type": "quantitative", "axis": null},
      "fill": {"field": "Month", "legend": null}
    }
  }
}`;
const X_SPEC_LAYER=`{
  "data": {"name": "dataset"},
  "transform": [{
    "joinaggregate": [{"op": "mean", "field": "Sales", "as": "Avg"}]
  }],
  "layer": [{
    "mark": {"type": "bar", "cornerRadiusEnd": 3},
    "encoding": {
      "x": {"field": "Month", "sort": null},
      "y": {"field": "Sales", "type": "quantitative"},
      "color": {
        "condition": {"test": "datum.Sales >= datum.Avg", "value": {"expr": "pbiColor(0)"}},
        "value": "#cfcfcf"
      }
    }
  }, {
    "mark": {"type": "rule", "strokeDash": [4, 3]},
    "encoding": {"y": {"field": "Avg", "type": "quantitative"}}
  }]
}`;
const X_SPEC_PARAM=`{
  "data": {"name": "dataset"},
  "params": [{
    "name": "pick",
    "select": {"type": "point", "fields": ["Channel"]},
    "bind": "legend"
  }],
  "mark": {"type": "line", "strokeWidth": 2.5},
  "encoding": {
    "x": {"field": "Month", "sort": null},
    "y": {"field": "Sales", "type": "quantitative"},
    "color": {"field": "Channel", "scale": {"scheme": "pbiColorNominal"}},
    "opacity": {
      "condition": {"param": "pick", "value": 1},
      "value": 0.15
    }
  }
}`;
const X_RIDGE=MON.map((m,i)=>({n:m,v:X_DAYS.filter((_,k)=>xDate(k).getUTCMonth()===i)}));

/* ---- categories ---- */
CATS.push(
 {id:'xflow',x:1,n:'Flow, network & hierarchy',d:'Follow volume from stage to stage, see who connects to whom, and open up an organization or product tree.'},
 {id:'xstat',x:1,n:'Distributions & targets',d:'Look at the spread behind an average, and at each measure against its own bands and target.'},
 {id:'xcomp',x:1,n:'Comparison & ranking',d:'Before and after, rank over time, two sides of one axis, and many measures at once.'},
 {id:'xpart',x:1,n:'Proportion, overlap & text',d:'Shares and nested hierarchies beyond pie and treemap, overlaps between groups, and words sized by count.'},
 {id:'xtime',x:1,n:'Calendars, time & finance',d:'Daily and hourly patterns, seasonal flow, price movement and time-range filtering.'},
 {id:'xkpi',x:1,n:'Gauges & live KPIs',d:'Progress toward a goal as tanks, rings and dials, plus a running ticker.'},
 {id:'xbuild',x:1,n:'Build your own',d:'When nothing fits: declare a visual in Vega-Lite with Deneb, or draw SVG and HTML from DAX measures.'}
);
QUEST.push(['flow','Show a flow'],['dist','See a distribution']);

/* ---- visuals ---- */
VIS.push(
/* ======================= FLOW ======================= */
{id:'sankey',n:'Sankey diagram',cat:'xflow',st:'appsource',ic:'sankey',goals:['flow','change','part'],
 best:'Bands whose width is the amount flowing from one stage to the next. Shows where volume comes from and where it ends up.',
 wells:[['Source','Traffic source'],['Destination','Landing page'],['Weight','Σ Sessions'],['Tooltips','']],uses:['Website traffic from source to outcome','Income statement: revenue to profit','Energy, budget or material flows'],avoid:'Cycles and very many small flows; group small ones into Other.',
 v:[
  V('Traffic to outcome','Five sources, three landing pages, three outcomes. Click a node to trace its flows.','Source: Channel · Destination: Page · Weight: Sessions · chain two hops by mapping Page → Outcome','sankey',X_SK),
  V('Income statement','Revenue by category flows into cost of goods, then expenses and operating profit.','Source: Line item · Destination: Parent line · Weight: Amount · color links by destination','sankey',X_PNL,{tag:'Finance'}),
  V('Gradient links','Each band fades from its source color to its destination color.','Format › Links › Color: gradient (source to destination)','sankey',{...X_SK2,grad:true},{tag:'Style'}),
  V('Trace one source','Paid search selected: its flows stay bright and everything else dims.','Click a node · Ctrl+click to add more','sankey',X_SK,{st:{hl:'1'}})
 ]},
{id:'chord',n:'Chord diagram',cat:'xflow',st:'appsource',ic:'chord',goals:['flow','rel'],
 best:'Flows between members of one group, in both directions, around a circle.',
 wells:[['From','Brand last year'],['To','Brand this year'],['Values','Σ Customers'],['Tooltips','']],uses:['Customers switching between brands','Trade between regions','Transfers between departments'],avoid:'More than about ten members; arcs get too thin to read.',
 v:[
  V('Customer switching','Who gained customers from whom. Ribbon color shows the bigger direction.','From: Previous brand · To: Current brand · Values: Customers','chord',{names:X_BRANDS,m:X_SWITCH,u:'',outL:'Lost to others',inL:'Won from others'}),
  V('Trade between regions','Exports in both directions between five regions.','From: Exporter · To: Importer · Values: Trade value','chord',{...X_TRADE,u:'$',outL:'Exports',inL:'Imports'}),
  V('One member selected','Only the flows that touch our brand stay bright.','Click an arc to select a member','chord',{names:X_BRANDS,m:X_SWITCH,u:'',outL:'Lost to others',inL:'Won from others'},{st:{hl:'0'}})
 ]},
{id:'network',n:'Network graph',cat:'xflow',st:'appsource',ic:'network',goals:['rel','flow'],
 best:'Nodes and links laid out by force, so clusters and hubs show up on their own.',
 wells:[['Source node','Product A'],['Target node','Product B'],['Weight','Orders together'],['Node color','Category'],['Node size','Σ Sales']],uses:['Products bought together','Who works with whom','Dependencies between systems'],avoid:'Thousands of nodes; filter to the strongest links first.',
 v:[
  V('Products bought together','Twenty products; links are orders containing both. Size is sales.','Source: Product A · Target: Product B · Weight: Orders together','net',{groups:CAT4,labels:5}),
  V('Hubs by connections','Node size by number of links, every node labeled in focus mode.','Format › Nodes › Size: Degree · Labels: On','net',{groups:CAT4,size:'deg',labels:8}),
  V('Select a node','Click a product to keep it and its neighbors bright.','Click a node · the visual cross-highlights the rest of the page','net',{groups:CAT4,labels:5},{st:{hl:'0'}})
 ]},
{id:'org-chart',n:'Org chart and hierarchy tree',cat:'xflow',st:'appsource',ic:'org',goals:['detail','part'],
 best:'A parent–child hierarchy drawn as cards or a tree you can open and close.',
 wells:[['ID','Employee ID'],['Parent ID','Manager ID'],['Label','Name'],['Details','Role, Team size']],uses:['Org charts and reporting lines','Product hierarchy with values','Cost center trees'],avoid:'Deep, wide trees in a small space; start collapsed and let readers open branches.',
 v:[
  V('Org chart: open a team','Leaders on the second row; click one to show their team.','ID: Employee · Parent ID: Manager · click a card to expand','org',{people:X_ORG},{st:{open:3},tag:'Expand'}),
  V('Leadership only','Collapsed to the first two levels, with team sizes as badges.','Format › Levels › Expanded: 2','org',{people:X_ORG}),
  V('Hierarchy tree with values','Category › Subcategory, with a bar per leaf. Click a category to fold it.','Hierarchy: Category › Subcategory · Values: Sales','htree',{tree:HP},{st:{col:[2,3]},tag:'Expand'})
 ]},

/* ======================= DISTRIBUTIONS & TARGETS ======================= */
{id:'histogram',n:'Histogram',cat:'xstat',st:'appsource',ic:'hist',goals:['dist','compare'],
 best:'Counts of values in equal-width bins: the shape of a distribution.',
 wells:[['Values','Order value'],['Bins','Count or width'],['Legend','Channel'],['Tooltips','']],uses:['Order value distribution','Delivery time spread','Response time buckets'],avoid:'Few observations; a dot plot shows them individually.',
 v:[
  V('Order values','Nine hundred orders in about twenty bins.','Values: Order value · Format › Bins: 20','hist',{groups:[{n:'Orders',v:X_ORD.on.concat(X_ORD.re)}],bins:20,u:'$'}),
  V('Two groups overlaid','Online and retail orders on the same bins, see-through so both show.','Legend: Channel · Format › Bars › Transparency: 40%','hist',{groups:[{n:'Online',v:X_ORD.on,c:1},{n:'Retail',v:X_ORD.re,c:2}],bins:20,u:'$'}),
  V('Mean, median and normal curve','Reference lines for the center and a fitted bell curve for comparison.','Analytics › Mean and Median lines · Format › Show normal curve','hist',{groups:[{n:'Orders',v:X_ORD.on.concat(X_ORD.re)}],bins:20,norm:true,stats:true,u:'$'},{tag:'Analytics'}),
  V('Change the bin count','Switch between 8, 16 and 32 bins to see how the shape holds up.','Format › Bins › Count (a field parameter makes it a reader choice)','hist',{groups:[{n:'Orders',v:X_ORD.on.concat(X_ORD.re)}],bins:16,binCtl:true,u:'$'},{tag:'Interactive'})
 ]},
{id:'box-whisker',n:'Box and whisker',cat:'xstat',st:'appsource',ic:'box',goals:['dist','compare'],
 best:'Median, quartiles, whiskers and outliers per group: spread at a glance.',
 wells:[['Category','Carrier'],['Sampling','Shipment'],['Values','Delivery days'],['Tooltips','']],uses:['Delivery times by carrier','Salaries by grade','Lead times by supplier'],avoid:'Readers new to quartiles; add a one-line legend or use a dot plot.',
 v:[
  V('Delivery days by carrier','Boxes from the 25th to the 75th percentile, whiskers to 1.5 × IQR, dots for outliers.','Category: Carrier · Sampling: Shipment ID · Values: Delivery days','box',{groups:X_DEL,u:'d',zero:true,yt:'Delivery days',mean:false}),
  V('With every point','Each shipment as a dot over a lighter box, so sample size shows.','Format › Data points: All, jittered','box',{groups:X_DEL,u:'d',zero:true,points:'jitter'}),
  V('Horizontal, sorted by median','Fastest carrier on top.','Format › Orientation: Horizontal · Sort by median','box',{groups:X_DEL,u:'d',zero:true,dir:'h',sort:true,yt:'Delivery days'}),
  V('Mean marker and side points','A diamond marks the mean; points sit beside each box.','Format › Mean: On · Points: Beside','box',{groups:X_DEL,u:'d',zero:true,mean:true,points:'side'})
 ]},
{id:'violin',n:'Violin and raincloud',cat:'xstat',st:'appsource',ic:'violin',goals:['dist','compare'],
 best:'Density curves mirrored into a violin. They show shapes a box hides, such as two peaks.',
 wells:[['Category','Device'],['Sampling','Session'],['Measure data','Minutes'],['Tooltips','']],uses:['Session length by device','Basket size by store type','Test scores by class'],avoid:'Small samples; the curve suggests more certainty than there is.',
 v:[
  V('Session length by device','The app has two peaks, quick checks and long browses, that a box plot would merge.','Category: Device · Sampling: Session · Measure: Minutes','violin',{groups:X_SESS,u:'',zero:true,yt:'Minutes per session'}),
  V('Violin with a box inside','Quartiles and median drawn inside each violin.','Format › Combo plot: Box','violin',{groups:X_SESS,u:'',zero:true,box:true}),
  V('Raincloud','Half violin, a slim box and the raw points, side by side.','Format › Violin: Half · Combo plot: Box · show points (barcode or jitter)','violin',{groups:X_SESS,u:'',zero:true,rain:true})
 ]},
{id:'bullet',n:'Bullet chart',cat:'xstat',st:'appsource',ic:'bullet',goals:['kpi','compare'],
 best:'A compact bar per measure against its target and qualitative bands. A gauge that fits in a row.',
 wells:[['Category','Measure name'],['Value','Actual'],['Target value','Target'],['Minimum / Needs improvement / Satisfactory / Good / Maximum','Band thresholds']],uses:['KPI scorecards','Sales vs quota by rep','Service levels vs SLA'],avoid:'One measure alone; a card with a reference label is lighter.',
 v:[
  V('KPI scorecard','Five measures, each on its own scale, with poor/fair/good bands.','Category: Measure · Value: Actual · Target value · band thresholds','bullet',{items:X_BUL}),
  V('Bar colored by status','Bar turns green, amber or red by percent of target.','Format › Data colors › fx: Rules on Actual ÷ Target','bullet',{items:X_BUL,status:true},{tag:'fx'}),
  V('Vertical bullets','Columns side by side, for a dashboard strip.','Format › Orientation: Vertical','bullet',{items:X_BUL,dir:'v'})
 ]},
{id:'parallel',n:'Parallel coordinates',cat:'xstat',st:'appsource',ic:'parcoord',goals:['rel','compare'],
 best:'One vertical axis per measure and one line per item, so trade-offs across many measures show.',
 wells:[['Category','Subcategory'],['Values','Sales, Profit, Units, Margin, Avg price'],['Legend','Category']],uses:['Product profiles across five measures','Store benchmarking','Comparing candidates on many criteria'],avoid:'More than about 30 lines without a selection to focus them.',
 v:[
  V('Subcategories across five measures','Lines colored by category. High sales but low margin shows as a falling line.','Values: one measure per axis · Legend: Category','parcoord',{...X_PAR}),
  V('Highlight one category','Bikes selected; the other lines step back.','Click a line to select its category','parcoord',{...X_PAR},{st:{hl:'0'}})
 ]},

/* ======================= COMPARISON & RANKING ======================= */
{id:'lollipop',n:'Lollipop and dot plot',cat:'xcomp',st:'appsource',ic:'lolli',goals:['compare','rank'],
 best:'A bar thinned to a line with a dot at the value: same comparison, much less ink.',
 wells:[['Category','Product'],['Values','Σ Sales']],uses:['Rankings with many items','Monthly values without heavy bars','Positive and negative change'],avoid:'When totals need to stack; use a stacked bar.',
 v:[
  V('Ranked products','Top twelve products, largest first.','Category: Product · Values: Sales · sort descending','lolli',{cats:TOP12.map(p=>p.n),v:TOP12.map(p=>p.v[0]),sort:true,u:'$'}),
  V('Vertical by month','Twelve months with values over every other dot.','Orientation: Vertical · Category: Month','lolli',{cats:MON,v:TY,dir:'v',u:'$'}),
  V('Diverging change','Growth vs last year by month, colored by direction.','Values: YoY % · Format › Colors › fx by sign','lolli',{cats:MON,v:YOY,dir:'v',div:true,u:'%',vn:'vs last year'},{tag:'fx'})
 ]},
{id:'dumbbell',n:'Dumbbell chart',cat:'xcomp',st:'appsource',ic:'dumbbell',goals:['change','compare'],
 best:'Two dots joined by a line: the gap between two values per item.',
 wells:[['Category','Country'],['Value 1','Σ Sales 2024'],['Value 2','Σ Sales 2025']],uses:['This year vs last year by country','Plan vs actual by team','Lowest vs highest price by line'],avoid:'More than two values per row; use a dot plot.',
 v:[
  V('2024 vs 2025 by country','Ten largest countries; the line is green when sales grew.','Category: Country · Values: Sales 2024, Sales 2025','dumbbell',{rows:X_CTRY,an:'2024',bn:'2025',u:'$',zero:false,sort:true}),
  V('Sorted by change','Biggest gain at the top.','Sort by Sales 2025 − Sales 2024','dumbbell',{rows:X_CTRY,an:'2024',bn:'2025',u:'$',zero:false,sort:'delta'}),
  V('Price range per subcategory','Lowest to highest product price, with the average marked.','Values: Min price, Avg price, Max price','dumbbell',{rows:X_PR,range:true,u:'$',zero:true,labels:false})
 ]},
{id:'slope',n:'Slope chart',cat:'xcomp',st:'appsource',ic:'slope',goals:['change','rank'],
 best:'Two columns of values joined by lines. Direction and steepness show change.',
 wells:[['Category','Region'],['Start value','Σ Sales 2024'],['End value','Σ Sales 2025']],uses:['Region sales year over year','Margin change by product line','Survey scores before and after'],avoid:'Many crossing lines; highlight the one that matters.',
 v:[
  V('Regions year over year','Four regions, labeled at both ends.','Category: Region · Values: Sales 2024, Sales 2025','slope',{rows:X_REGY,an:'2024',bn:'2025',u:'$'}),
  V('One line highlighted','E-bike margin jumped while most lines eased.','Format › Colors › fx: highlight one category','slope',{rows:X_MARG,an:'2024 margin',bn:'2025 margin',u:'%',hl:2},{tag:'fx'})
 ]},
{id:'bump',n:'Bump chart',cat:'xcomp',st:'appsource',ic:'bump',goals:['rank','trend'],
 best:'Rank over time, one line per item. Who overtook whom.',
 wells:[['X-axis','Quarter'],['Legend','Subcategory'],['Rank by','Σ Sales']],uses:['Product rank by quarter','League tables','Search rank of keywords'],avoid:'When the size of the gap matters; rank hides it.',
 v:[
  V('Subcategory rank by quarter','E-bike climbs from fourth to first.','X-axis: Quarter · Legend: Subcategory · rank measure','bump',{...X_BUMP,u:'$'}),
  V('Follow one line','Others in gray so the climb stands out.','Format › Colors › highlight one series','bump',{...X_BUMP,u:'$',hl:2},{tag:'fx'})
 ]},
{id:'tornado',n:'Tornado chart',cat:'xcomp',st:'appsource',ic:'tornado',goals:['compare','change'],
 best:'Two bars back to back from a center line: two groups, or the low and high case of each driver.',
 wells:[['Group','Age band'],['Values','Σ Women, Σ Men'],['Legend','']],uses:['Customer age pyramid','Sensitivity of profit to each driver','Survey: agree vs disagree'],avoid:'Comparing values that do not share a unit.',
 v:[
  V('Customers by age and gender','The classic population pyramid, labeled in the middle.','Group: Age band · Values: Women, Men','tornado',{...X_AGE,ln:'Women',rn:'Men',u:'',foot:'Customers'}),
  V('Profit sensitivity','How far operating profit moves when each driver hits its low or high case.','Group: Driver · Values: Low case, High case · base line at plan','tornado',{...X_SENS,u:'$'},{tag:'Finance'})
 ]},
{id:'radar',n:'Radar chart',cat:'xcomp',st:'appsource',ic:'radar',goals:['compare','rel'],
 best:'Several scores on spokes around a center, joined into a shape per item.',
 wells:[['Category','Attribute'],['Y-axis','Score'],['Legend','Brand']],uses:['Product scorecards','Skill profiles','Competitor comparison'],avoid:'Reading exact values or comparing more than three shapes.',
 v:[
  V('Two products compared','Our bikes against the market leader on six attributes.','Category: Attribute · Y-axis: Score · Legend: Brand','radar',{axes:X_RAX,series:X_RAD,max:10}),
  V('Circular grid','A rounder look with one series.','Format › Grid › Shape: Circle','radar',{axes:X_RAX,series:[X_RAD[0]],max:10,grid:'circle'}),
  V('Small multiples','One radar per category, same scale.','Small multiples: Category','radar',{axes:X_RAX,multi:X_RADM,max:10},{tag:'Small multiples'})
 ]},

/* ======================= PROPORTION, OVERLAP & TEXT ======================= */
{id:'sunburst',n:'Sunburst',cat:'xpart',st:'appsource',ic:'sunburst',goals:['part'],
 best:'A pie that keeps going outward: each ring is the next hierarchy level.',
 wells:[['Group','Category › Subcategory › Product'],['Values','Σ Sales'],['Tooltips','']],uses:['Sales by category and subcategory','Spend by department and account','Website paths'],avoid:'Comparing outer segments precisely; use a treemap or bars.',
 v:[
  V('Two levels','Categories inside, subcategories outside.','Group: Category, Subcategory · Values: Sales','sunburst',{tree:HP,depth:2}),
  V('Three levels','Products on the outer ring.','Group: Category, Subcategory, Product','sunburst',{tree:HP,depth:3}),
  V('Click to zoom','Bikes opened as the new center. Click a segment to go in, the center to come out.','Click a segment · click the center to go up','sunburst',{tree:HP,depth:2},{st:{sb:[0]},tag:'Zoom'})
 ]},
{id:'circle-packing',n:'Circle packing',cat:'xpart',st:'appsource',ic:'pack',goals:['part','compare'],
 best:'Circles inside circles, sized by value. A friendlier treemap for hierarchies.',
 wells:[['Category','Category › Subcategory › Product'],['Values','Σ Sales']],uses:['Product portfolio by category','Budget by department and team','Topics within themes'],avoid:'Comparing sizes precisely; circles waste space and hide small differences.',
 v:[
  V('Nested categories','Category, subcategory and product, every product a circle.','Category: hierarchy · Values: Sales','pack',{}),
  V('Zoomed into Components','Click a category to zoom in; click the background or the button to go back.','Click a circle to zoom','pack',{},{st:{pk:1},tag:'Zoom'})
 ]},
{id:'mekko',n:'Mekko chart',cat:'xpart',st:'appsource',ic:'mekko',goals:['part','compare'],
 best:'A 100% stacked column whose widths are also data: share within each column and size of each column at once.',
 wells:[['X-axis','Region'],['Legend','Channel'],['Y-axis','Σ Sales']],uses:['Market share by segment and region','Revenue mix by product and country','Headcount by function and location'],avoid:'Many columns or segments; labels stop fitting.',
 v:[
  V('Region by channel','Column width is region sales; segments are channel share.','X-axis: Region · Legend: Channel · Values: Sales','mekko',{cols:REG4,segs:CH,m:REGCH,u:'$'}),
  V('Value labels','Labels show amounts instead of shares.','Format › Data labels › Display: Value','mekko',{cols:REG4,segs:CH,m:REGCH,u:'$',labels:'value'})
 ]},
{id:'waffle',n:'Waffle chart',cat:'xpart',st:'appsource',ic:'waffle',goals:['part','kpi'],
 best:'A 10 × 10 grid where each square is one percent. Shares that are easy to count.',
 wells:[['Values','Repeat rate'],['Legend','']],uses:['Single percentages people should feel','Category shares out of 100','Comparing a rate across groups'],avoid:'Values that need decimals.',
 v:[
  V('One percentage','Sixty-eight squares of a hundred filled.','Values: Repeat purchase rate','waffle',{pct:68,n:'of customers bought again within 12 months'}),
  V('Category shares','Each category gets its share of the hundred squares.','Legend: Category · Values: Sales','waffle',{parts:CAT4.map((n,i)=>({n,v:CAT4S[i]})),u:'$'}),
  V('Small multiples','The same rate across three channels.','Small multiples: Channel · Values: Orders with a discount %','waffle',{items:[{n:'Online',pct:34},{n:'Retail',pct:22},{n:'Partner',pct:41}]},{tag:'Small multiples'})
 ]},
{id:'pictogram',n:'Pictogram (infographic)',cat:'xpart',st:'appsource',ic:'picto',goals:['part','compare'],
 best:'Icons stand in for units, so a number reads as people or things.',
 wells:[['Category','Region'],['Measure','Σ Customers'],['Shape','Person icon']],uses:['“7 in 10 customers…” statements','Customers per region in icons','Headline infographics'],avoid:'Precise comparisons; partial icons are hard to judge.',
 v:[
  V('7 in 10','A ratio told with ten people.','Measure: Weekly riders ÷ Customers · Format › Shape: Person','picto',{mode:'people',v:7,of:10,title:'customers ride at least weekly',sub:'Survey of 2,400 customers, Oct 2025',n:'Weekly riders'}),
  V('Icons per region','Each icon is 500 customers; the last one is cut to size.','Category: Region · Measure: Customers · Format › Units per icon: 500','picto',{rows:HG.root.c.map((r,i)=>({n:r.n,v:agg(r)[1]})),unit:500,unitN:'customers',u:''})
 ]},
{id:'aster',n:'Aster plot',cat:'xpart',st:'appsource',ic:'aster',goals:['kpi','compare'],
 best:'A donut whose slice width is weight and slice length is score, with the overall score in the middle.',
 wells:[['Category','Attribute'],['Y-axis','Score'],['Weight','Importance']],uses:['Customer experience scores','Supplier assessments','Health indexes'],avoid:'More than eight or nine slices.',
 v:[
  V('Customer experience score','Six attributes; wider slices matter more to the total.','Category: Attribute · Y-axis: Score · Weight: Importance','aster',{items:[{n:'Product range',s:82,w:2},{n:'Price',s:64,w:1.5},{n:'Delivery',s:71,w:1.5},{n:'Support',s:88,w:1},{n:'Website',s:76,w:1},{n:'Returns',s:58,w:1}],cl:'Overall'}),
  V('Equal weights','Every slice the same width, so only length varies.','Weight: empty','aster',{items:[{n:'Range',s:82,w:1},{n:'Price',s:64,w:1},{n:'Delivery',s:71,w:1},{n:'Support',s:88,w:1},{n:'Website',s:76,w:1},{n:'Returns',s:58,w:1},{n:'Stores',s:69,w:1}],cl:'Average'})
 ]},
{id:'rose',n:'Rose (polar area) chart',cat:'xpart',st:'appsource',ic:'rose',goals:['trend','part'],
 best:'Equal-angle wedges whose area follows the value; good for cycles such as months.',
 wells:[['Category','Month'],['Values','Σ Sales'],['Legend','Channel']],uses:['Seasonality across months','Wind or traffic by direction','Activity by hour'],avoid:'Precise comparisons; outer wedges look bigger than they are.',
 v:[
  V('Sales by month','Twelve wedges, darker for bigger months.','Category: Month · Values: Sales · color saturation by value','rose',{cats:MON,series:[{n:'Sales',v:TY}],u:'$'}),
  V('Stacked by channel','Channels stacked within each wedge.','Legend: Channel','rose',{cats:MON,series:CH.map((n,i)=>({n,v:CHM[i]})),u:'$'})
 ]},
{id:'venn',n:'Venn diagram',cat:'xpart',st:'appsource',ic:'venn',goals:['part','rel'],
 best:'Overlapping circles for groups that share members, with counts in each region.',
 wells:[['Sets','Channel'],['Values','Customer count']],uses:['Customers who shop in several channels','Overlap of product owners','Audience overlap between campaigns'],avoid:'More than three sets.',
 v:[
  V('Two groups','Customers who bought a bike, booked a service, or both.','Sets: Bought a bike, Booked a service · Values: Customers','venn',{sets:[{n:'Bought a bike',v:4200},{n:'Booked a service',v:2600}],ov:{ab:1500},vn:'Customers'}),
  V('Three channels','Customers by where they shopped; the middle shopped everywhere.','Sets: Online, Retail, Partner','venn',{sets:[{n:'Online',v:5200},{n:'Retail',v:4100},{n:'Partner',v:1900}],ov:{ab:1400,ac:600,bc:500,abc:260},vn:'Customers'})
 ]},
{id:'word-cloud',n:'Word cloud',cat:'xpart',st:'appsource',ic:'words',goals:['detail','rel'],
 best:'Words sized by how often they appear: a quick read of open text.',
 wells:[['Category','Phrase'],['Values','Mentions'],['Color','Sentiment']],uses:['Themes in customer feedback','Search terms','Ticket topics'],avoid:'Decisions that need exact counts; pair it with a bar chart.',
 v:[
  V('Feedback by sentiment','Phrases from reviews, colored positive to negative.','Category: Phrase · Values: Mentions · Format › Colors › fx by Sentiment','words',{words:X_WORDS}),
  V('Colored by topic','Rotated words and a topic legend.','Format › Rotate text: On · Legend: Topic','words',{words:X_WORDS,color:'group',groups:['Service','Product','Price & offers','Online'],rot:true})
 ]},

/* ======================= CALENDARS, TIME & FINANCE ======================= */
{id:'calendar',n:'Calendar heatmap',cat:'xtime',st:'appsource',ic:'cal',goals:['trend','detail'],
 best:'One square per day, shaded by value. Weekly rhythm, seasons and one-off spikes in one view.',
 wells:[['Date','Order date'],['Values','Σ Orders']],uses:['Daily orders over a year','Website visits per day','Incidents per day'],avoid:'Values that need exact reading; add a tooltip or table.',
 v:[
  V('A year of daily orders','Weekends darker, a summer bulge and a Black Friday spike.','Date: Order date · Values: Orders','cal',{days:X_DAYS,vn:'Orders'}),
  V('One month in detail','November as a calendar page with values in each day.','Filter to one month · Format › Show values','cal',{days:X_DAYS,month:10,vn:'Orders'})
 ]},
{id:'heat-grid',n:'Heat grid and punch card',cat:'xtime',st:'appsource',ic:'heatgrid',goals:['trend','rel'],
 best:'Two categories crossed into a grid, shaded or sized by value.',
 wells:[['Rows','Weekday'],['Columns','Hour'],['Values','Σ Orders']],uses:['Orders by weekday and hour','Ticket load by team and day','Store traffic heat'],avoid:'Long category lists on both axes.',
 v:[
  V('Weekday by hour','Lunch and evening peaks on weekdays, a midday hump at weekends.','Rows: Weekday · Columns: Hour · Values: Orders','heatgrid',{rows:XDN,cols:X_HRL,m:X_HG,vn:'Orders'}),
  V('Punch card','Circle size instead of shade.','Format › Shape: Circle sized by value','heatgrid',{rows:XDN,cols:X_HRL,m:X_HG,punch:true,vn:'Orders'})
 ]},
{id:'stream',n:'Stream graph',cat:'xtime',st:'appsource',ic:'stream',goals:['trend','part'],
 best:'Stacked areas around a moving center line, for rhythm and rise or fall rather than exact totals.',
 wells:[['Category','Month'],['Values','Σ Sales'],['Legend','Subcategory']],uses:['Seasonal mix of product lines','Topics in the news','Listening by genre'],avoid:'Exact values; the center baseline makes reading heights hard.',
 v:[
  V('Wiggle','Seven subcategories over 24 months; E-bike swells.','Category: Month · Legend: Subcategory · Format › Offset: Wiggle','stream',{...X_STREAM,offset:'wiggle',u:'$'}),
  V('Silhouette','Symmetric about the middle.','Format › Offset: Silhouette','stream',{...X_STREAM,offset:'silhouette',u:'$'})
 ]},
{id:'candlestick',n:'Candlestick',cat:'xtime',st:'appsource',ic:'candle',goals:['trend','detail'],
 best:'Open, high, low and close per period: price movement and volatility.',
 wells:[['Date','Trading day'],['Open','Open'],['High','High'],['Low','Low'],['Close','Close'],['Volume','Volume']],uses:['Share price','Commodity and FX prices','Daily min/max of any metric'],avoid:'Non-financial audiences; a line with a range band is easier.',
 v:[
  V('Price with a zoom slider','Six months of trading. Drag the slider or across the plot to zoom.','Date · Open · High · Low · Close · Format › Zoom slider: On','candle',{data:X_OHLC,u:'$.'},{tag:'Zoom',zoom:true,brush:true,z:[.6,1]}),
  V('Volume and moving average','Volume bars below and a 10-day average line.','Volume: Volume · Analytics › Moving average: 10 days','candle',{data:X_OHLC,u:'$.',vol:true,ma:10},{tag:'Analytics',zoom:true,brush:true,z:[.45,1]})
 ]},
{id:'timeline-slicer',n:'Timeline slicer',cat:'xtime',st:'appsource',ic:'timeline',goals:['filter','trend'],
 best:'A slicer that looks like a calendar strip: pick a period or a range by clicking.',
 wells:[['Time','Date']],uses:['Choose a reporting period','Compare a promotion window','Zoom a page to a season'],avoid:'Non-date fields; use a slicer.',
 v:[
  V('Months, pick a range','Click a month, then another, to set the range; the bars below show what is in it.','Time: Date · Granularity: Month','timeline',{months:X_M24,v:X_TL,sel:[14,19]},{tag:'Interactive'}),
  V('Quarter granularity','Switch between year, quarter and month in the visual.','Format › Granularity: Quarter (change it in the visual)','timeline',{months:X_M24,v:X_TL,sel:[12,23],gran:'quarter'},{tag:'Interactive'})
 ]},

/* ======================= GAUGES & LIVE KPIs ======================= */
{id:'liquid-gauge',n:'Liquid fill gauge',cat:'xkpi',st:'appsource',ic:'liquid',goals:['kpi'],
 best:'A tank that fills to the value, with a gentle wave. Progress with personality.',
 wells:[['Value','Σ Sales'],['Max value','Goal']],uses:['Goal progress on a cover page','Capacity used','Fundraising totals'],avoid:'Comparisons between many values; use bars.',
 v:[
  V('Progress to goal','Sixty-two percent of the quarterly goal.','Value: Sales QTD · Max value: Quarter goal','liquid',{v:.62,n:'Quarterly goal',vn:'of goal',items:[{n:'Quarterly goal',v:.62,sub:'$1.9M of $3.1M'}]}),
  V('Three tanks','One gauge per channel, same scale.','Small multiples or three visuals side by side','liquid',{items:[{n:'Online',v:.82,c:1,sub:'$3.1M of $3.8M'},{n:'Retail',v:.47,c:2,sub:'$2.2M of $4.7M'},{n:'Partner',v:.23,c:3,sub:'$0.4M of $1.7M'}],vn:'of goal'})
 ]},
{id:'radial-bar',n:'Radial bar chart',cat:'xkpi',st:'appsource',ic:'radial',goals:['kpi','compare'],
 best:'Bars bent into circles: progress rings, or columns around a center.',
 wells:[['Category','Measure'],['Values','% of target']],uses:['Several goals in one compact view','Monthly totals in a circle','Fitness-style progress'],avoid:'Comparing ring lengths; outer rings look longer.',
 v:[
  V('Progress rings','Four goals as concentric rings.','Category: Measure · Values: % of target','radial',{items:[{n:'Sales',v:.86,sub:'$9.3M of $10.8M'},{n:'Orders',v:.73},{n:'Margin',v:.64},{n:'NPS',v:.91}]}),
  V('Radial columns','Monthly sales as columns around a circle.','Category: Month · Values: Sales','radial',{mode:'columns',cats:MON,v:TY,u:'$',cl:'2025 sales'})
 ]},
{id:'tachometer',n:'Tachometer (dial gauge)',cat:'xkpi',st:'appsource',ic:'tacho',goals:['kpi'],
 best:'A needle on a dial with colored bands, ticks and a target.',
 wells:[['Value','Utilization'],['Start value','0'],['End value','100'],['Range 2 start / Range 3 start','Band thresholds'],['Target value','Target']],uses:['Utilization or capacity','Speed-style operational KPIs','Scores against a target'],avoid:'Trends; a dial shows one moment.',
 v:[
  V('Bands and target','Red, amber and green bands with a target mark.','Value · Start · End · Range thresholds · Target value','tacho',{v:72,min:0,max:100,u:'%',n:'Workshop utilization',target:80,bands:[{to:50,c:'crit',n:'Under-used'},{to:75,c:'warn',n:'Fair'},{to:100,c:'good',n:'Healthy'}]}),
  V('Gradient fill','A filled arc in the brand ramp instead of bands.','Format › Range colors: gradient','tacho',{v:81,min:0,max:100,u:'',n:'Customer satisfaction',target:85})
 ]},
{id:'ticker',n:'Ticker and scroller',cat:'xkpi',st:'appsource',ic:'ticker',goals:['kpi','detail'],
 best:'Numbers or messages that scroll past, like a news ticker. Pauses on hover.',
 wells:[['Category','Measure name'],['Measure','Value'],['Measure deviation','vs last year']],uses:['Wall-board KPIs','Live order feed','Alerts on a cover page'],avoid:'Anything readers must study; moving text is hard to read.',
 v:[
  V('KPI ticker','Eight measures scroll by, with change arrows.','Category: Measure name · Measure: Value · Deviation: vs LY %','ticker',{items:X_TICK,title:'2025 · all regions'},{tag:'Motion'}),
  V('Live feed','A vertical scroller of recent events.','Format › Scroll direction: Up','ticker',{mode:'v',items:X_FEED,title:'Live from stores and web'},{tag:'Motion'})
 ]},

/* ======================= BUILD YOUR OWN ======================= */
{id:'deneb',n:'Deneb (Vega-Lite)',cat:'xbuild',st:'build',ic:'deneb',goals:['rel','trend','dist'],
 best:'Write a Vega or Vega-Lite specification inside Power BI and get almost any chart, themed from the report.',
 wells:[['Values','Any columns and measures']],uses:['Ridgeline, beeswarm and other niche charts','Layered annotations','Visuals your organization standardizes as templates'],avoid:'Teams without someone to maintain JSON specs.',
 v:[
  V('Ridgeline plot','Daily order distributions per month as overlapping curves.','Get more visuals › Deneb · Values: Month, Orders · Edit › Vega-Lite spec','deneb',{mode:'ridge',rows:X_RIDGE,spec:X_SPEC_RIDGE},{tag:'Code'}),
  V('Layered bars and rule','A joinaggregate average drives both the rule and the bar colors; colors come from the report theme.','Deneb · Vega-Lite layer · pbiColor() for theme colors','deneb',{mode:'layer',cats:MON,v:TY,spec:X_SPEC_LAYER},{tag:'Code'}),
  V('Interactive legend','A selection parameter bound to the legend fades the other lines. Click a channel.','Deneb · params with "bind": "legend" · cross-filtering on','deneb',{mode:'param',cats:MON,series:CH.map((n,i)=>({n,v:CHM[i]})),spec:X_SPEC_PARAM},{tag:'Interactive'})
 ]},
{id:'svg-measures',n:'SVG measures in tables',cat:'xbuild',st:'build',ic:'svgtable',goals:['detail','kpi'],
 best:'DAX measures that return SVG images, so a table can carry sparklines, bullets and status icons.',
 wells:[['Columns','Product, Sales, Trend SVG, Target SVG, Margin']],uses:['Scorecards in a table','Inline trends per row','Status columns'],avoid:'Very long tables; every image is rendered per row.',
 v:[
  V('Sparklines and bullets','Trend, target and margin bars drawn by measures.','Measure returns "data:image/svg+xml;utf8,<svg…>" · Data category: Image URL','svgtable',{rows:X_SVT},{tag:'Technique'}),
  V('Progress pills and status','A percent-to-goal pill and a status label per row.','SVG measure for the pill · conditional icons for status','svgtable',{rows:X_SVT,mode:'pill'},{tag:'Technique'})
 ]},
{id:'html-content',n:'HTML content',cat:'xbuild',st:'appsource',ic:'htmlc',goals:['kpi','detail'],
 best:'Measures that return HTML and CSS, rendered as styled cards or rich text.',
 wells:[['Values','HTML measure'],['Granularity','']],uses:['Branded KPI tiles','Narratives with live values','Custom layouts that cards cannot do'],avoid:'Heavy logic in DAX strings; keep the HTML small and templated.',
 v:[
  V('KPI tiles from HTML','Three tiles built by one measure with brand styles.','Get more visuals › HTML Content · Values: measure returning <div> markup','htmlc',{cards:[{l:'Sales',v:fmt(TYS,'$'),d:pctCh(TYS,LYS),s:'vs last year',ic:'cart',tr:TY},{l:'Profit',v:fmt(PRS,'$'),d:pctCh(PRS,PRLS),s:'vs last year',ic:'store',tr:PROF},{l:'Orders',v:fmt(ORD),d:pctCh(ORD,ORDL),s:'vs last year',ic:'handshake',tr:UNITS}]}),
  V('Rich text with live values','A paragraph where every number is a measure.','HTML measure with <b> spans for each value','htmlc',{mode:'text',t:{k:'Year to date · all regions',s:fmt(TYS,'$'),g:pctCh(TYS,LYS).toFixed(1)+'%',top:'Bikes',topv:fmt(CAT4S[0],'$'),weak:'Clothing',weakv:'3.1%'},parts:CAT4.map((n,i)=>({n,v:CAT4S[i]}))})
 ]}
);
