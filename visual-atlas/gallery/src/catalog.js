/* ============================================================
   Catalog: categories, visuals, variants
   variant: {t title, d description, h how-to (steps split by ·),
             k renderer, o options, tag, dm drill-mode default,
             z initial zoom window, zoom slider, brush, play, map}
   ============================================================ */
const B=(s,mode,x)=>({t:'bar',mode:mode||'cluster',s,...(x||{})});
const Ln=(s,x)=>({t:'line',s,...(x||{})});
const S=(n,v,c,x)=>({n,v,c,...(x||{})});
const DS=(n,k,c,x)=>({n,k,c,...(x||{})});
const V=(t,d,h,k,o,x)=>({t,d,h,k,o,...(x||{})});

/* --- derived series used by several variants --- */
const CATM=(()=>{const r=rng(61);const tot=sum0(CAT4S);return CAT4.map((c,k)=>({n:c,v:TY.map((t,i)=>r100(t*CAT4S[k]/tot*(.86+r()*.28)*(k===3?1+.035*i:k===1?1-.012*i:1)))}));})();
const REGM=(()=>{const r=rng(64);const tot=sum0(REG4S);return REG4.map((n,ri)=>({n,v:TY.map(t=>r100(t*REG4S[ri]/tot*(.84+r()*.32)))}));})();
const CH36=(()=>{const r=rng(65);return CH.map((c,k)=>S36.map((t,i)=>r100(t*[.34+i*.004,.46-i*.004,.2][k]*(.92+r()*.16))));})();
const FC=(()=>{const act=S36.slice(12);const cats=[...M36.slice(12),'Jan 2026','Feb','Mar','Apr','May','Jun'];const v=[...act,null,null,null,null,null,null];
  const f=Array(30).fill(null);f[23]=act[23];for(let k=0;k<6;k++)f[24+k]=r100(act[12+k]*1.1);
  const lo=f.map((x,i)=>x==null?null:i===23?x:r100(x*(1-.05-.025*(i-24)))),hi=f.map((x,i)=>x==null?null:i===23?x:r100(x*(1+.05+.025*(i-24))));return {cats,v,f,lo,hi};})();
const AN=(()=>{const b=S36.slice(),v=b.slice();v[9]=r100(b[9]*1.4);v[22]=r100(b[22]*.64);return {v,elo:b.map(x=>r100(x*.9)),ehi:b.map(x=>r100(x*1.1)),an:[9,22]};})();
const ERRQ={lo:TYQ.map(v=>r100(v*.9)),hi:TYQ.map(v=>r100(v*1.08))};
const CASHM=WF_CASH.slice(1,13).map(s=>s.v);
const TOP12=[...PRODS].sort((a,b)=>b.v[0]-a.v[0]).slice(0,12);
const PARETO=(()=>{const t=sum0(PRODS.map(p=>p.v[0]));let c=0;return TOP12.map(p=>{c+=p.v[0];return Math.round(c/t*1000)/10;});})();
const RUN=(()=>{let c=0;return TY.map(v=>(c+=v));})();
const YOY=TY.map((v,i)=>Math.round((v/LY[i]-1)*1000)/10);
const MARG=TY.map((v,i)=>Math.round(PROF[i]/v*1000)/10);
const LIKS=LIK.lv.map((n,k)=>S(n,LIK.v[k],['dv1','dv2','dv3','dv4','dv5'][k],{inkDark:k>0&&k<4}));
const LIKDIV=[S('Neutral',LIK.v[2].map(v=>-v/2),'dv3',{nl:1,inkDark:1}),S('Disagree',LIK.v[1].map(v=>-v),'dv2',{inkDark:1}),S('Strongly disagree',LIK.v[0].map(v=>-v),'dv1'),S('Neutral',LIK.v[2].map(v=>v/2),'dv3',{inkDark:1}),S('Agree',LIK.v[3],'dv4',{inkDark:1}),S('Strongly agree',LIK.v[4],'dv5')];
const REGT=REG4S.map((v,i)=>r100(v*[1.04,.96,1.08,1.12][i]));
const STORESK=STORES.map(s=>({...s,k:s.y/s.x>9?0:s.y/s.x>7.4?1:2}));
const BRIDGE=(()=>{const d=TYS-LYS;const f=[.95,.5,.25,-.42,-.2];const st=[{n:'2024 sales',t:'total',v:LYS}];['New customers','Upsell','Price change','Churn','Discounts'].forEach((n,i)=>st.push({n,v:r100(d*f[i])}));st.push({n:'Currency',v:r100(d*(1-sum0(f)))});st.push({n:'2025 sales',t:'total'});return st;})();
const PNL=[{n:'Revenue',t:'total',v:TYS},{n:'Cost of goods',v:-r100(TYS*.57)},{n:'Gross profit',t:'total'},{n:'Marketing',v:-r100(TYS*.1)},{n:'Admin',v:-r100(TYS*.085)},{n:'R&D',v:-r100(TYS*.055)},{n:'Operating profit',t:'total'}];
const BRK=(()=>{const d=TYS-LYS;return [{n:'2024',t:'total',v:LYS},{n:'Bikes',v:r100(d*.62)},{n:'Components',v:r100(d*.21)},{n:'Clothing',v:r100(-d*.09)},{n:'Accessories',v:r100(d*.18)},{n:'Services',v:r100(d*.08)},{n:'2025',t:'total'}];})();
const BSI=HG.root.c.map((r,i)=>({n:r.n,v:fmt(agg(r)[0],'$'),g:pctCh(agg(r)[0],agg(r)[2]),ic:['globe','globe','globe','globe'][i]}));
const BSC=CH.map((c,i)=>({n:c,v:fmt(CHM[i].reduce((a,b)=>a+b,0),'$'),g:[8,-3,5][i],ic:['cart','store','handshake'][i]}));
const BSP=HP.root.c.map((c,i)=>({n:c.n,v:fmt(agg(c)[0],'$'),g:[6,4,-2,9][i],ic:catIcon(c.n)}));

const CATS=[
 {id:'bars',n:'Bars & columns',d:'Compare values across categories. Bars for long labels and rankings, columns for time.'},
 {id:'trend',n:'Lines, areas & combos',d:'Show change over time, and how two measures move together.'},
 {id:'flow',n:'Rank, flow & change',d:'Explain how a total moved, who leads each period, and where a process leaks.'},
 {id:'part',n:'Part-to-whole',d:'Show how the pieces add up to a total.'},
 {id:'rel',n:'Distribution & schedules',d:'Find correlations, clusters and outliers; lay tasks out on a timeline.'},
 {id:'maps',n:'Maps',d:'Put values on geography, from bubbles to heat, 3D columns and custom shapes.'},
 {id:'kpi',n:'Cards, KPIs & gauges',d:'Lead with the number that matters and how it compares with its goal.'},
 {id:'tables',n:'Tables & matrices',d:'Exact values, conditional formatting and expandable hierarchies.'},
 {id:'filters',n:'Slicers',d:'Put filters on the canvas so readers can slice the whole page.'},
 {id:'ai',n:'AI visuals',d:'Let the model find drivers, choose the next split, and write the summary.'},
 {id:'embed',n:'Apps, code & reports',d:'Bring paginated reports, Power Platform apps, R and Python into the page.'},
 {id:'elements',n:'Report elements',d:'Images, text, shapes, buttons and navigation that hold a report together.'}
];
const QUEST=[['compare','Compare categories'],['trend','Show a trend'],['part','Part of a whole'],['rank','Rank items'],['change','Explain a change'],['rel','Find relationships'],['geo','Show where'],['kpi','Track a target'],['detail','Exact numbers'],['filter','Filter the page'],['ai','Find drivers'],['action','Take action']];

/* shared well sets */
const WB=[['Y-axis','Category'],['X-axis','Σ Sales'],['Legend',''],['Small multiples',''],['Tooltips','Σ Profit']];
const WC=[['X-axis','Date › Month'],['Y-axis','Σ Sales'],['Legend',''],['Small multiples',''],['Tooltips','Σ Profit']];
const WCL=[['X-axis','Date › Month'],['Y-axis','Σ Sales'],['Legend','Channel'],['Small multiples',''],['Tooltips','']];

/* drill + zoom helpers that every bar/column visual gets */
const drillCols=(mode,dir)=>V('Drill down: Year › Quarter › Month','Turn on drill mode (↓) and click a '+(dir==='h'?'bar':'column')+'. Use ⇊ for the next level across all years, or ⇓ to expand all one level.','Put a date hierarchy on the axis · Visual header ↓ turns on drill mode · ↑ drills back up','cart',{dir,drill:HD,layers:[mode==='cluster'?B([DS('Sales',0,1),DS('Profit',1,2)]):B([DS('Profit',1,1),DS('Cost',3,2)],mode)],u:'$'},{tag:'Drill',dm:true});
const drillProd=(mode,dir)=>V('Drill down: Category › Subcategory › Product','Click a '+(dir==='h'?'bar':'column')+' in drill mode to open its subcategories, then products.','Axis: Category, Subcategory, Product · Visual header ↓ · click a data point',
  'cart',{dir,drill:HP,sort:'desc',layers:[mode==='cluster'?B([DS('Sales',0,1)],'cluster',{labels:'out'}):B([DS('Profit',1,1),DS('Cost',3,2)],mode)],u:'$'},{tag:'Drill',dm:true});

const VIS=[
/* ======================= BARS & COLUMNS ======================= */
{id:'clustered-column',n:'Clustered column chart',cat:'bars',st:'ga',ic:'ccol',goals:['compare','trend','rank'],
 best:'Compare one or more measures side by side across categories or time periods.',
 wells:WCL,uses:['Monthly sales against last year','Headcount by department and level','Tickets opened vs closed each week'],avoid:'More than about 12 categories, or long labels; switch to a clustered bar chart.',
 v:[
  V('Basic: sales by month','One measure across twelve periods. The workhorse.','X-axis: Month · Y-axis: Sales','cart',{cats:MON,layers:[B([S('Sales',TY)])],u:'$'}),
  V('Two measures with a legend','This year beside last year. Each measure gets a series color and a legend entry.','Y-axis: Sales TY, Sales LY','cart',{cats:QTR,layers:[B([S('2025',TYQ,1),S('2024',LYQ,2)],'cluster',{labels:'out'})],u:'$'}),
  V('Sorted with data labels','Top products, largest first, value on each cap.','More options (…) › Sort axis › Sales, descending · Format › Data labels: On','cart',{cats:TOPP.map(p=>p.n.replace(' ',' ')),sort:'desc',layers:[B([S('Sales',TOPP.map(p=>p.v[0]))],'cluster',{labels:'out'})],u:'$'}),
  V('Rule-based colors','Months at or above target in green, below in red.','Format › Columns › Color › fx › Rules, based on Sales − Target','cart',{cats:MON,colorBy:{k:'rule',f:(v,i)=>v>=TARGET[i]?'good':'crit'},legItems:[{n:'At or above target',c:'good'},{n:'Below target',c:'crit'}],legend:true,layers:[B([S('Sales',TY,1,{nl:1})])],u:'$'},{tag:'fx'}),
  V('Gradient by value','Color saturation follows the value, so the eye finds the peaks first.','Format › Columns › Color › fx › Gradient','cart',{cats:SUBS.slice(0,10).map(s=>s.n),colorBy:{k:'grad'},layers:[B([S('Sales',SUBS.slice(0,10).map(s=>s.v[0]))])],u:'$'},{tag:'fx'}),
  V('Average and constant lines','A dynamic average line plus a fixed target from the Analytics pane.','Analytics › Average line · Analytics › Constant line (value 1M)','cart',{cats:MON,layers:[B([S('Sales',TY)])],ref:[{v:'avg',n:'Average'},{v:1000000,n:'Target',c:'c2'}],u:'$'},{tag:'Analytics'}),
  V('Error bars','Forecast range per quarter as upper and lower bounds.','Analytics › Error bars › Upper bound: Sales high · Lower bound: Sales low','cart',{cats:QTR,layers:[B([S('Forecast',TYQ)])],err:{lo:ERRQ.lo,hi:ERRQ.hi},u:'$'},{tag:'Analytics'}),
  V('Negative values','Net cash flow above and below zero, colored by sign.','Format › Columns › Color › fx › Rules (value < 0 → red)','cart',{cats:MON,colorBy:{k:'rule',f:v=>v>=0?'c1':'crit'},layers:[B([S('Net cash',CASHM)])],u:'$'},{tag:'fx'}),
  drillCols('cluster','v'),
  V('Zoom slider','Thirty-six months with a zoom slider. Drag the handles, or drag across the plot to zoom.','Format › X-axis › Zoom slider: On','cart',{cats:M36,layers:[B([S('Sales',S36)])],u:'$'},{tag:'Zoom',zoom:true,brush:true,z:[.58,1]}),
  V('Small multiples by region','One small chart per region, sharing a y-axis scale.','Small multiples: Region · Format › Small multiples › Layout','sm',{panels:REGQ.map(r=>({n:r.n,cats:QTR,layers:[B([S('2025',r.ty,1),S('2024',r.ly,2)])]})),u:'$'},{tag:'Small multiples'}),
  V('Focus on one category','Everything muted except the month that matters.','Format › Columns › Color › fx › Rules (Month = Nov → accent, else gray)','cart',{cats:MON,colorBy:{k:'hl',i:10},layers:[B([S('Sales',TY)],'cluster',{labels:false})],ref:[{v:'max',n:'Peak'}],u:'$'},{tag:'fx'})
 ]},
{id:'clustered-bar',n:'Clustered bar chart',cat:'bars',st:'ga',ic:'cbar',goals:['compare','rank'],
 best:'Horizontal bars side by side. Best for rankings and long category names.',
 wells:WB,uses:['Top 10 customers by revenue','Survey questions by agreement','Sales by store against target'],avoid:'Time series; time reads left to right, so use columns or a line.',
 v:[
  V('Ranking with data labels','Largest first, values at the tip of each bar.','Sort axis › Sales, descending · Data labels: On','cart',{dir:'h',cats:TOPP.map(p=>p.n),sort:'desc',layers:[B([S('Sales',TOPP.map(p=>p.v[0]))],'cluster',{labels:'out'})],u:'$'}),
  V('Two measures per category','This year and last year for each category.','X-axis: Sales 2025, Sales 2024','cart',{dir:'h',cats:CAT4,layers:[B([S('2025',CAT4S,1),S('2024',CAT4S.map((v,i)=>r100(v/[1.14,1.1,.97,1.16][i])),2)])],u:'$'}),
  V('Long category names','Bars keep long labels readable without rotating them.','Y-axis: Survey question · X-axis: % agree','cart',{dir:'h',cats:LIK.cats,sort:'desc',layers:[B([S('% agree or strongly agree',LIK.cats.map((_,i)=>LIK.v[3][i]+LIK.v[4][i]))],'cluster',{labels:'out'})],u:'%'}),
  V('Target markers (bullet style)','Error bars with upper = lower = target draw a marker across each bar.','Analytics › Error bars › Upper and lower bound: Target · Bar style','cart',{dir:'h',cats:REG4,layers:[B([S('Sales',REG4S)])],err:{style:'marker',t:REGT},u:'$'},{tag:'Technique'}),
  V('Values inside the bars','Labels sit inside the bar end and switch outside when the bar is short.','Data labels › Position: Inside end','cart',{dir:'h',cats:SUBS.slice(0,8).map(s=>s.n),sort:'desc',layers:[B([S('Sales',SUBS.slice(0,8).map(s=>s.v[0]))],'cluster',{labels:'in'})],u:'$'}),
  V('Average line','Which regions sit above the company average.','Analytics › Average line','cart',{dir:'h',cats:CITIES.slice(0,9).map(c=>c.n),sort:'desc',layers:[B([S('Sales',CITIES.slice(0,9).map(c=>c.v[0]))])],ref:[{v:'avg',n:'Avg'}],u:'$'},{tag:'Analytics'}),
  drillProd('cluster','h'),
  V('Small multiples by channel','The same ranking repeated for each sales channel.','Small multiples: Channel','sm',{dir:'h',cols:3,panels:CH.map((c,ci)=>({n:c,cats:CAT4,layers:[B([S('Sales',CAT4S.map(v=>r100(v*[.42,.39,.19][ci])))])]})),u:'$'},{tag:'Small multiples'}),
  V('Above or below average','Rule colors compare each bar with the average.','Bars › Color › fx › Rules based on a measure: Sales − Average','cart',{dir:'h',cats:CITIES.slice(0,9).map(c=>c.n),sort:'desc',colorBy:{k:'rule',f:v=>v>=sum0(CITIES.slice(0,9).map(c=>c.v[0]))/9?'c1':'muted-mark'},layers:[B([S('Sales',CITIES.slice(0,9).map(c=>c.v[0]))])],ref:[{v:'avg',n:'Avg'}],u:'$'},{tag:'fx'})
 ]},
{id:'stacked-column',n:'Stacked column chart',cat:'bars',st:'ga',ic:'scol',goals:['compare','part','trend'],
 best:'Columns split into segments: the total and its composition in one view.',
 wells:WCL,uses:['Sales by month split by channel','Headcount by team and contract type','Energy use by source per quarter'],avoid:'Comparing middle segments precisely; only the bottom segment shares a baseline.',
 v:[
  V('Channel mix by month','Three channels stacked into each monthly total.','Legend: Channel','cart',{cats:MON,layers:[B(CH.map((c,i)=>S(c,CHM[i])),'stack')],u:'$'}),
  V('Total labels','The stack total sits on top of each column.','Format › Total labels: On','cart',{cats:QTR,layers:[B(CH.map((c,i)=>S(c,CHQ[i])),'stack',{total:true})],u:'$'}),
  V('Segment labels','Each segment labelled where it fits; small ones stay in the tooltip.','Data labels: On · Position: Inside center','cart',{cats:QTR,layers:[B(CH.map((c,i)=>S(c,CHQ[i])),'stack',{labels:true})],u:'$'}),
  V('Positive and negative stacks','Inflows stack above zero and outflows below.','Y-axis: Inflow, Payroll, Suppliers (as negative values)','cart',{cats:QTR,layers:[B([S('Receipts',TYQ.map(v=>r100(v*.92)),1),S('Payroll',TYQ.map(v=>-r100(v*.38)),2),S('Suppliers',TYQ.map(v=>-r100(v*.44)),3)],'stack')],u:'$'}),
  drillCols('stack','v'),
  V('Small multiples by region','Channel stacks repeated per region.','Small multiples: Region','sm',{panels:REG4.map((r,ri)=>({n:r,cats:QTR,layers:[B(CH.map((c,i)=>S(c,CHQ[i].map(v=>r100(v*REG4S[ri]/sum0(REG4S))))),'stack')]})),u:'$'},{tag:'Small multiples'}),
  V('Sorted by total','Stacks ordered by their total size.','More options (…) › Sort axis › Sales','cart',{cats:REG4,sort:'desc',layers:[B(CH.map((c,i)=>S(c,REGCH[i])),'stack',{total:true})],u:'$'}),
  V('Zoom slider on 36 months','Long stacked series with a zoom window.','X-axis › Zoom slider: On','cart',{cats:M36,layers:[B(CH.map((c,i)=>S(c,CH36[i])),'stack')],u:'$'},{tag:'Zoom',zoom:true,brush:true,z:[.66,1]})
 ]},
{id:'stacked-bar',n:'Stacked bar chart',cat:'bars',st:'ga',ic:'sbar',goals:['compare','part','rank'],
 best:'Horizontal stacks for totals and composition with readable labels.',
 wells:[['Y-axis','Region'],['X-axis','Σ Sales'],['Legend','Channel'],['Small multiples',''],['Tooltips','']],uses:['Sales by region split by channel','Time spent per project by activity','Budget by department and cost type'],avoid:'Many segments; past five or six, group the rest into Other.',
 v:[
  V('Composition by region','Channel segments inside each regional total.','Legend: Channel','cart',{dir:'h',cats:REG4,layers:[B(CH.map((c,i)=>S(c,REGCH[i])),'stack')],u:'$'}),
  V('Total labels','Totals at the end of each bar.','Format › Total labels: On','cart',{dir:'h',cats:REG4,sort:'desc',layers:[B(CH.map((c,i)=>S(c,REGCH[i])),'stack',{total:true})],u:'$'}),
  V('Diverging stacks (Likert)','Disagree values entered as negatives so agreement grows right and disagreement left.','Y-axis: Question · X-axis: response % (disagree as negative) · Legend: Response','cart',{dir:'h',cats:LIK.cats,layers:[B(LIKDIV,'stack')],u:'%'},{tag:'Technique'}),
  drillCols('stack','h'),
  V('Small multiples by channel','One stacked bar chart per channel.','Small multiples: Channel','sm',{dir:'h',cols:3,panels:CH.map((c,ci)=>({n:c,cats:CAT4,layers:[B([S('Profit',CAT4P.map(v=>r100(v*[.42,.39,.19][ci])),1),S('Cost',CAT4S.map((v,i)=>r100((v-CAT4P[i])*[.42,.39,.19][ci])),2)],'stack')]})),u:'$'},{tag:'Small multiples'}),
  V('Highlight one series','Gray every channel except the one under discussion.','Format › Bars › Color: set the other series to gray','cart',{dir:'h',cats:REG4,colorBy:{k:'hls',i:0},layers:[B(CH.map((c,i)=>S(c,REGCH[i])),'stack')],u:'$'},{tag:'fx'}),
  V('Segment labels','Values inside segments when they fit.','Data labels: On','cart',{dir:'h',cats:REG4,layers:[B(CH.map((c,i)=>S(c,REGCH[i])),'stack',{labels:true})],u:'$'})
 ]},
{id:'100-stacked-column',n:'100% stacked column chart',cat:'bars',st:'ga',ic:'pcol',goals:['part','trend'],
 best:'Every column reaches 100%, so you compare shares rather than totals.',
 wells:WCL,uses:['Channel share by quarter','Device mix of sessions per month','Share of tickets by priority'],avoid:'When the size of the total matters; a stacked column keeps it.',
 v:[
  V('Channel share by quarter','Shares of each channel within every quarter.','Legend: Channel','cart',{cats:QTR,layers:[B(CH.map((c,i)=>S(c,CHQ[i])),'pct')]}),
  V('Percent labels','Each segment labelled with its share.','Data labels: On','cart',{cats:QTR,layers:[B(CH.map((c,i)=>S(c,CHQ[i])),'pct',{labels:true})]}),
  V('Share across twelve months','Month-by-month mix shows the drift toward online.','X-axis: Month','cart',{cats:MON,layers:[B(CH.map((c,i)=>S(c,CHM[i])),'pct')]}),
  V('Two-part share','Online versus everything else reads faster than a pie.','Legend: Is online (Yes / No)','cart',{cats:QTR,layers:[B([S('Online',CHQ[0],1),S('Store and partner',CHQ[1].map((v,i)=>v+CHQ[2][i]),'muted-mark')],'pct',{labels:true})]}),
  drillCols('pct','v'),
  V('Small multiples by region','Share comparison repeated per region.','Small multiples: Region','sm',{panels:REG4.map((r,ri)=>({n:r,cats:QTR,layers:[B(CH.map((c,i)=>S(c,CHQ[i].map((v,q)=>r100(v*(1+(ri-1.5)*(i-1)*.12*(q+1)/4))))),'pct')]}))},{tag:'Small multiples'})
 ]},
{id:'100-stacked-bar',n:'100% stacked bar chart',cat:'bars',st:'ga',ic:'pbar',goals:['part','compare'],
 best:'Horizontal 100% stacks. The standard way to show survey and Likert results.',
 wells:[['Y-axis','Question'],['X-axis','% of responses'],['Legend','Response'],['Small multiples',''],['Tooltips','']],uses:['Survey responses by question','Win/loss share by sales rep','Project completion (done vs remaining)'],avoid:'Categories whose totals differ a lot when the total matters.',
 v:[
  V('Survey responses','Five-point agreement with a diverging palette.','Legend: Response, sorted Strongly disagree → Strongly agree','cart',{dir:'h',cats:LIK.cats,layers:[B(LIKS,'pct')]}),
  V('Percent labels','Shares inside segments that are wide enough.','Data labels: On','cart',{dir:'h',cats:LIK.cats,layers:[B(LIKS,'pct',{labels:true})]}),
  V('Channel share by region','Mix of channels for each region.','Legend: Channel','cart',{dir:'h',cats:REG4,layers:[B(CH.map((c,i)=>S(c,REGCH[i])),'pct',{labels:true})]}),
  V('Progress bars','Done versus remaining work per project.','X-axis: Done, Remaining · color remaining gray','cart',{dir:'h',cats:['Data model','Report pages','Security','UAT','Training'],layers:[B([S('Done',[92,64,30,12,4],1),S('Remaining',[8,36,70,88,96],'track')],'pct',{labels:true})]}),
  drillProd('pct','h'),
  V('Small multiples by year','The same share split for three years.','Small multiples: Year','sm',{dir:'h',cols:3,panels:['2023','2024','2025'].map((y,yi)=>({n:y,cats:CAT4,layers:[B(CH.map((c,i)=>S(c,CAT4S.map((v,k)=>r100(v*[.3+yi*.06,.5-yi*.05,.2-yi*.01][i]*(1+k*.05*(i-1)))))),'pct')]}))},{tag:'Small multiples'})
 ]},

/* ======================= TREND ======================= */
{id:'line',n:'Line chart',cat:'trend',st:'ga',ic:'line',goals:['trend','compare'],
 best:'The shape of a series over time. Carries forecasting and anomaly detection.',
 wells:[['X-axis','Date › Month'],['Y-axis','Σ Sales'],['Secondary y-axis',''],['Legend',''],['Small multiples',''],['Tooltips','']],uses:['Daily active users over a year','Revenue this year against last year','Inventory level with reorder threshold'],avoid:'Unordered categories; lines imply continuity between points.',
 v:[
  V('Basic trend','Three years of monthly sales.','X-axis: Month (continuous) · Y-axis: Sales','cart',{cats:M36,layers:[Ln([S('Sales',S36)])],u:'$'}),
  V('This year vs last year','Last year dashed so the current year leads.','Y-axis: Sales 2025, Sales 2024 · Lines › Line style: Dashed','cart',{cats:MON,layers:[Ln([S('2025',TY,1),S('2024',LY,2,{dash:1})])],u:'$'}),
  V('Markers and data labels','A value on every point, for short series.','Format › Markers: On · Data labels: On','cart',{cats:MON,layers:[Ln([S('Sales',TY)],{mk:true,labels:'all'})],u:'$'}),
  V('Smooth line','Monotone curve through the points.','Format › Lines › Interpolation: Smooth','cart',{cats:MON,layers:[Ln([S('2025',TY,1),S('2024',LY,2)],{curve:'smooth'})],u:'$'}),
  V('Stepped line','Values that hold until they change, like a list price.','Format › Lines › Stepped: On','cart',{cats:MON,zero:false,layers:[Ln([S('List price',[2999,2999,2999,3199,3199,3199,3199,3099,3099,3249,3249,3249])],{curve:'step'})],u:'$'}),
  V('Series labels instead of a legend','Names sit at the end of each line.','Format › Series labels: On · Legend: Off','cart',{cats:MON,endLabels:true,layers:[Ln(CATM.map((c,i)=>S(c.n,c.v,i+1)))],u:'$'}),
  V('Forecast','Six months ahead with a 95% confidence band.','Analytics › Forecast · Forecast length 6 · Confidence interval 95%','cart',{cats:FC.cats,layers:[Ln([S('Sales',FC.v,1,{f:FC.f,lo:FC.lo,hi:FC.hi})])],ref:[{x:24,n:'Forecast'}],u:'$'},{tag:'Analytics'}),
  V('Anomaly detection','Points outside the expected range are flagged, with the range shaded.','Analytics › Find anomalies · Sensitivity 70%','cart',{cats:M36,layers:[Ln([S('Sales',AN.v,1,{elo:AN.elo,ehi:AN.ehi,anom:AN.an})])],u:'$'},{tag:'AI'}),
  V('Trend line','Linear trend over the visible points.','Analytics › Trend line','cart',{cats:M36,layers:[Ln([S('Sales',S36)],{trend:true})],u:'$'},{tag:'Analytics'}),
  V('Min and max lines','Range of the series marked with two lines.','Analytics › Min line · Max line','cart',{cats:MON,layers:[Ln([S('Sales',TY)],{mk:true})],ref:[{v:'max',n:'Max'},{v:'min',n:'Min'}],u:'$'},{tag:'Analytics'}),
  V('Shaded target zone','A constant line with the area above it shaded.','Analytics › Constant line › Shade area: After','cart',{cats:MON,layers:[Ln([S('Sales',TY)],{mk:'end',labels:'end'})],ref:[{v:850000,n:'Target',shade:'above',line:true}],u:'$'},{tag:'Analytics'}),
  V('Error band','Upper and lower bounds drawn as a shaded band.','Analytics › Error bars › Error band: On','cart',{cats:MON,layers:[Ln([S('Sales',TY)])],err:{style:'band',lo:TY.map(v=>r100(v*.92)),hi:TY.map(v=>r100(v*1.07))},u:'$'},{tag:'Analytics'}),
  V('Drill down: Year › Quarter › Month','Click a point in drill mode to move from years to quarters to months.','X-axis: Date hierarchy · Visual header ↓, ⇊, ⇓','cart',{drill:HD,layers:[Ln([DS('Sales',0,1),DS('Profit',1,2)],{mk:true})],u:'$'},{tag:'Drill',dm:true}),
  V('Zoom slider','Drag the handles or drag across the plot to zoom.','Format › X-axis › Zoom slider: On','cart',{cats:M36,layers:[Ln([S('Sales',S36)],{mk:true})],u:'$'},{tag:'Zoom',zoom:true,brush:true,z:[0,.5]}),
  V('Small multiples by region','One line per panel, shared scale.','Small multiples: Region','sm',{panels:REGM.map(r=>({n:r.n,cats:MON,layers:[Ln([S('Sales',r.v)])]})),u:'$'},{tag:'Small multiples'}),
  V('Secondary y-axis','Sales in dollars and margin in percent. Read with care: two scales can suggest relationships that are not there.','Secondary y-axis: Margin %','cart',{cats:MON,layers:[Ln([S('Sales',TY,1)]),Ln([S('Margin %',MARG,2)],{y2:true})],u:'$',u2:'%',zero:false},{tag:'Dual axis'}),
  V('Focus on one series','Color one line, gray the rest.','Lines › Color per series · set others to gray','cart',{cats:MON,colorBy:{k:'focus',i:3},endLabels:true,layers:[Ln(CATM.map((c,i)=>S(c.n,c.v,i+1)),{mk:'end'})],u:'$'},{tag:'fx'})
 ]},
{id:'area',n:'Area chart',cat:'trend',st:'ga',ic:'area',goals:['trend'],
 best:'A line with the area beneath shaded, emphasizing volume over time.',
 wells:WC,uses:['Website sessions over a year','Cumulative signups','Two series overlapping, such as plan vs actual'],avoid:'More than two overlapping series; use lines instead.',
 v:[
  V('Basic area','One series with a light wash beneath.','X-axis: Month · Y-axis: Sales','cart',{cats:M36,layers:[Ln([S('Sales',S36)],{area:'wash',fo:.16})],u:'$'}),
  V('Overlapping series','Two layered areas; the overlap stays visible.','Y-axis: Sales 2025, Sales 2024','cart',{cats:MON,layers:[Ln([S('2025',TY,1),S('2024',LY,2)],{area:'wash',fo:.14})],u:'$'}),
  V('End marker and label','The latest value called out at the right edge.','Markers: last point only · Data labels: last point','cart',{cats:MON,layers:[Ln([S('Sales',TY)],{area:'wash',mk:'end',labels:'end',fo:.16})],u:'$'}),
  V('Drill down: Year › Quarter › Month','Area that follows the date hierarchy as you drill.','X-axis: Date hierarchy · drill mode','cart',{drill:HD,layers:[Ln([DS('Sales',0,1)],{area:'wash',mk:true,fo:.16})],u:'$'},{tag:'Drill',dm:true}),
  V('Zoom slider','Brush or drag the slider to focus on a window.','X-axis › Zoom slider: On','cart',{cats:M36,layers:[Ln([S('Sales',S36)],{area:'wash',fo:.16})],u:'$'},{tag:'Zoom',zoom:true,brush:true,z:[.33,.75]}),
  V('Small multiples by region','Regional trends with a shared scale.','Small multiples: Region','sm',{panels:REGM.map(r=>({n:r.n,cats:MON,layers:[Ln([S('Sales',r.v)],{area:'wash',fo:.16})]})),u:'$'},{tag:'Small multiples'})
 ]},
{id:'stacked-area',n:'Stacked area chart',cat:'trend',st:'ga',ic:'sarea',goals:['trend','part'],
 best:'Series stacked on top of one another: the total trend and each contribution.',
 wells:WCL,uses:['Sales by channel over time','Cloud spend by service','Population by age band'],avoid:'Reading a middle band precisely; only the bottom band has a flat baseline.',
 v:[
  V('Channel volume over time','Three channels building the monthly total.','Legend: Channel','cart',{cats:MON,layers:[Ln(CH.map((c,i)=>S(c,CHM[i])),{area:'stack'})],u:'$'}),
  V('Smooth stacked','Curved edges for a softer read.','Lines › Interpolation: Smooth','cart',{cats:MON,layers:[Ln(CH.map((c,i)=>S(c,CHM[i])),{area:'stack',curve:'smooth'})],u:'$'}),
  V('Five traffic sources','More bands, ordered with the steadiest at the bottom.','Legend: Source · order by size','cart',{cats:MON,layers:[Ln(TRAF.n.map((n,i)=>S(n,TRAF.v[i].map(v=>v*1200))),{area:'stack'})]}),
  V('Zoom slider on 36 months','Three years of channel volume with a zoom window.','X-axis › Zoom slider: On','cart',{cats:M36,layers:[Ln(CH.map((c,i)=>S(c,CH36[i])),{area:'stack'})],u:'$'},{tag:'Zoom',zoom:true,brush:true,z:[.5,1]}),
  V('Small multiples by region','Stacks repeated per region.','Small multiples: Region','sm',{panels:REG4.map((r,ri)=>({n:r,cats:MON,layers:[Ln(CH.map((c,i)=>S(c,CHM[i].map(v=>r100(v*REG4S[ri]/sum0(REG4S))))),{area:'stack'})]})),u:'$'},{tag:'Small multiples'})
 ]},
{id:'100-stacked-area',n:'100% stacked area chart',cat:'trend',st:'ga',ic:'parea',goals:['trend','part'],
 best:'Shares over time, every period filled to 100%.',
 wells:WCL,uses:['Traffic source share by month','Device mix over time','Market share trend'],avoid:'When absolute volume changes a lot; the shape hides it.',
 v:[
  V('Traffic source share','Five sources as shares of monthly sessions.','Legend: Source','cart',{cats:MON,layers:[Ln(TRAF.n.map((n,i)=>S(n,TRAF.v[i])),{area:'pct'})]}),
  V('Channel share','Three channels; online grows its share through the year.','Legend: Channel','cart',{cats:MON,layers:[Ln(CH.map((c,i)=>S(c,CHM[i])),{area:'pct'})]}),
  V('Smooth edges','Curved boundaries between the bands.','Lines › Interpolation: Smooth','cart',{cats:MON,layers:[Ln(CH.map((c,i)=>S(c,CHM[i])),{area:'pct',curve:'smooth'})]}),
  V('Small multiples by region','Share bands per region.','Small multiples: Region','sm',{panels:REG4.map((r,ri)=>({n:r,cats:MON,layers:[Ln(CH.map((c,i)=>S(c,CHM[i].map((v,m)=>r100(v*(1+(ri-1.5)*(i-1)*.1*m/11))))),{area:'pct'})]}))},{tag:'Small multiples'})
 ]},
{id:'line-stacked-column',n:'Line and stacked column chart',cat:'trend',st:'ga',ic:'lscol',goals:['trend','compare','part'],
 best:'Stacked columns for composition plus a line for a related measure.',
 wells:[['X-axis','Date › Month'],['Column y-axis','Σ Sales'],['Line y-axis','Margin %'],['Column legend','Channel'],['Small multiples',''],['Tooltips','']],uses:['Sales by channel with margin %','Units by product with target','Hours by team with utilization'],avoid:'Unrelated measures on two axes; readers will infer a link.',
 v:[
  V('Channel stacks + margin line','Margin % on a secondary axis over the stacked sales.','Line y-axis: Margin % · Format › Secondary y-axis: On','cart',{cats:MON,layers:[B(CH.map((c,i)=>S(c,CHM[i])),'stack'),Ln([S('Margin %',MARG,'ink')],{y2:true,mk:true})],u:'$',u2:'%'},{tag:'Dual axis'}),
  V('Stacks with a target line','Target on the same axis as the stacks.','Line y-axis: Target · Secondary y-axis: Off','cart',{cats:MON,layers:[B(CH.map((c,i)=>S(c,CHM[i])),'stack'),Ln([S('Target',TARGET,'ink',{dash:1})])],u:'$'}),
  V('Labels on the line only','Data labels limited to the line series.','Data labels › Apply settings to: Margin % only','cart',{cats:QTR,layers:[B(CH.map((c,i)=>S(c,CHQ[i])),'stack'),Ln([S('Margin %',q(MARG).map(v=>Math.round(v/3*10)/10),'ink')],{y2:true,mk:'big',labels:'all'})],u:'$',u2:'%'}),
  V('Drill down: Year › Quarter › Month','Profit and cost stacks with units on the line, all following the drill.','Date hierarchy on X-axis · drill mode','cart',{drill:HD,layers:[B([DS('Profit',1,1),DS('Cost',3,2)],'stack'),Ln([DS('Units',2,'ink')],{y2:true,mk:true})],u:'$'},{tag:'Drill',dm:true}),
  V('Zoom slider','Combo with a 36-month zoom window.','X-axis › Zoom slider: On','cart',{cats:M36,layers:[B(CH.map((c,i)=>S(c,CH36[i])),'stack'),Ln([S('Total',S36,'ink')])],u:'$'},{tag:'Zoom',zoom:true,brush:true,z:[.66,1]}),
  V('Small multiples by region','One combo per region.','Small multiples: Region','sm',{panels:REG4.map((r,ri)=>({n:r,cats:QTR,layers:[B(CH.map((c,i)=>S(c,CHQ[i].map(v=>r100(v*REG4S[ri]/sum0(REG4S))))),'stack'),Ln([S('Target',TYQ.map(v=>r100(v*REG4S[ri]/sum0(REG4S)*.95)),'ink',{dash:1})])]})),u:'$'},{tag:'Small multiples'})
 ]},
{id:'line-clustered-column',n:'Line and clustered column chart',cat:'trend',st:'ga',ic:'lccol',goals:['trend','compare','change'],
 best:'Side-by-side columns with a line, often growth or a running total.',
 wells:[['X-axis','Date › Month'],['Column y-axis','Σ Sales 2025, Σ Sales 2024'],['Line y-axis','YoY %'],['Small multiples',''],['Tooltips','']],uses:['This year vs last year with growth %','Actual vs budget with variance','Pareto analysis of defects'],avoid:'Lines and columns with unrelated units unless the secondary axis is clearly labelled.',
 v:[
  V('TY vs LY with growth %','Columns compare the years; the line shows the growth rate.','Line y-axis: YoY % · Secondary y-axis: On','cart',{cats:MON,layers:[B([S('2025',TY,1),S('2024',LY,2)]),Ln([S('YoY %',YOY,'ink')],{y2:true,mk:true})],u:'$',u2:'%'},{tag:'Dual axis'}),
  V('Pareto chart','Products sorted by sales with the cumulative share and an 80% line.','Sort by Sales · Line: cumulative % (visual calculation RUNNINGSUM) · Constant line 80% on secondary axis','cart',{cats:TOP12.map(p=>p.n),layers:[B([S('Sales',TOP12.map(p=>p.v[0]))]),Ln([S('Cumulative %',PARETO,'ink')],{y2:true,mk:true})],ref:[{v:80,n:'80%',y2:true,nv:1,c:'crit'}],u:'$',u2:'%'},{tag:'Technique'}),
  V('Running total line','Monthly sales with the year-to-date total.','Line: RUNNINGSUM([Sales]) as a visual calculation','cart',{cats:MON,layers:[B([S('Sales',TY)]),Ln([S('Year to date',RUN,'ink')],{y2:true})],u:'$',u2:'$'},{tag:'Visual calc'}),
  V('Actual vs target with variance','Actual and target columns with the variance on the line.','Column y-axis: Actual, Target · Line: Variance %','cart',{cats:QTR,layers:[B([S('Actual',TYQ,1),S('Target',q(TARGET),'muted-mark')],'cluster',{labels:'out'}),Ln([S('Variance %',TYQ.map((v,i)=>Math.round((v/q(TARGET)[i]-1)*1000)/10),'ink')],{y2:true,mk:'big'})],u:'$',u2:'%'}),
  V('Drill down: Year › Quarter › Month','Sales and profit columns with units, through the hierarchy.','Date hierarchy · drill mode','cart',{drill:HD,layers:[B([DS('Sales',0,1),DS('Profit',1,2)]),Ln([DS('Units',2,'ink')],{y2:true,mk:true})],u:'$'},{tag:'Drill',dm:true}),
  V('Small multiples by region','Year-over-year columns and a target line per region.','Small multiples: Region','sm',{panels:REGQ.map(r=>({n:r.n,cats:QTR,layers:[B([S('2025',r.ty,1),S('2024',r.ly,2)]),Ln([S('Target',r.ly.map(v=>r100(v*1.08)),'ink',{dash:1})])]})),u:'$'},{tag:'Small multiples'})
 ]},

/* ======================= FLOW & CHANGE ======================= */
{id:'ribbon',n:'Ribbon chart',cat:'flow',st:'ga',ic:'ribbon',goals:['rank','trend'],
 best:'Stacked columns re-sorted every period so the leader sits on top; ribbons show rank changes.',
 wells:[['X-axis','Quarter'],['Y-axis','Σ Sales'],['Legend','Subcategory'],['Tooltips','']],uses:['Which product line leads each quarter','Brand share rank over time','Top channels by month'],avoid:'More than six or seven series; the ribbons tangle.',
 v:[
  V('Rank changes by quarter','E-bikes climb from last to first over two years.','Legend: Subcategory','ribbon',{cats:RIB.cats,s:RIB.n,v:RIB.v}),
  V('Data labels in the columns','Values printed where segments are tall enough.','Data labels: On','ribbon',{cats:RIB.cats.slice(4),s:RIB.n,v:RIB.v.map(a=>a.slice(4)),labels:true}),
  V('Solid ribbons','Lower transparency makes the flows the subject.','Ribbons › Transparency: 40%','ribbon',{cats:RIB.cats,s:RIB.n,v:RIB.v,op:.62}),
  V('Highlight a series','Click a ribbon to highlight it across every period.','Select a ribbon or legend item','ribbon',{cats:RIB.cats,s:RIB.n,v:RIB.v},{st:{hl:2}})
 ]},
{id:'waterfall',n:'Waterfall chart',cat:'flow',st:'ga',ic:'wfall',goals:['change'],
 best:'A running total: how increases and decreases move a starting value to an end value.',
 wells:[['Category','Driver'],['Breakdown',''],['Y-axis','Σ Change'],['Tooltips','']],uses:['Revenue bridge from last year to this year','Profit and loss walk','Headcount movement (hires, leavers, transfers)'],avoid:'Many small steps; group them into Other.',
 v:[
  V('Revenue bridge','Last year to this year by driver.','Category: Driver · Y-axis: Change · totals set by the visual','wfall',{steps:BRIDGE}),
  V('Breakdown by category','The Breakdown well explains the change between two periods.','Category: Year · Breakdown: Category','wfall',{steps:BRK}),
  V('Profit and loss walk','Revenue down to operating profit with subtotals.','Subtotals need a sort-order column and DAX measures','wfall',{steps:PNL},{tag:'Technique'}),
  V('Monthly cash movement','Opening balance, monthly net flows, closing balance.','Category: Month · Y-axis: Net cash flow','wfall',{steps:WF_CASH,labels:false}),
  V('Y-axis not starting at zero','A raised minimum makes small drivers visible. Say so on the page: bar lengths no longer compare to zero.','Format › Y-axis › Range › Minimum','wfall',{steps:BRIDGE,ymin:Math.floor(LYS*.94/250000)*250000}),
  V('Custom total color','Sentiment colors for increase, decrease and total can each be changed.','Format › Sentiment colors › Total','wfall',{steps:BRIDGE,totc:7})
 ]},
{id:'funnel',n:'Funnel',cat:'flow',st:'ga',ic:'funnel',goals:['change','part'],
 best:'Sequential stages that narrow, like a sales pipeline.',
 wells:[['Category','Stage'],['Values','Count of deals'],['Tooltips','']],uses:['Lead to closed-won pipeline','Checkout drop-off','Hiring stages from applicants to offers'],avoid:'Stages that are not sequential, or values that grow between stages.',
 v:[
  V('Sales pipeline','Five stages from lead to closed won.','Category: Stage · Values: Deals','funnel',{stages:PIPE}),
  V('Percent of first stage','Each stage relative to the top of the funnel.','Data labels › Label contents: Data value, percent of first','funnel',{stages:PIPE,pct:'first'}),
  V('Percent of previous stage','Step-to-step conversion.','Data labels › Label contents: Data value, percent of previous','funnel',{stages:PIPE,pct:'prev'}),
  V('Conversion rate label','First-to-last conversion summarized.','Format › Conversion rate label: On','funnel',{stages:PIPE,conv:true}),
  V('Ordinal shading','Darker stages carry fewer, more valuable deals.','Colors › fx › Gradient on stage order','funnel',{stages:PIPE,grad:true},{tag:'fx'}),
  V('Color per stage','A different color for every stage.','Colors › Show all: On','funnel',{stages:PIPE,vary:true})
 ]},

/* ======================= PART TO WHOLE ======================= */
{id:'pie',n:'Pie chart',cat:'part',st:'ga',ic:'pie',goals:['part'],
 best:'Shares of a whole, for a handful of categories.',
 wells:[['Legend','Category'],['Values','Σ Sales'],['Details',''],['Tooltips','']],uses:['Sales by category (four or five slices)','Budget split by department','Responses: yes / no / unsure'],avoid:'More than six slices, or comparing similar sizes; use a bar chart.',
 v:[
  V('Shares with a side legend','Four categories with the legend on the right.','Legend: Category · Format › Legend › Position: Right','pie',{cats:CAT4,v:CAT4S,legend:'right',labels:'in',u:'$'}),
  V('Labels outside with leader lines','Category name and share next to every slice.','Detail labels › Position: Outside · Label contents: Category, percent of total','pie',{cats:CAT4,v:CAT4S,labels:'out',u:'$'}),
  V('Category, value and share','Detail labels with all three values.','Detail labels › Label contents: All detail labels','pie',{cats:CAT4,v:CAT4S,labels:'detail',u:'$'}),
  V('Top 5 plus Other','Small slices folded into Other.','Filters › Top N 5 by Sales, plus an Other group in DAX','pie',{cats:SUBS.map(s=>s.n),v:SUBS.map(s=>s.v[0]),topN:5,labels:'out',u:'$'},{tag:'Technique'}),
  V('Selected slice','Click a slice: it stays bright and the rest dim, as when it filters other visuals.','Select a slice (Ctrl for several)','pie',{cats:CAT4,v:CAT4S,legend:'right',u:'$'},{st:{hl:2}}),
  V('Drill down: Category › Subcategory','Click a slice in drill mode to split it.','Legend: Category › Subcategory hierarchy · drill mode','pie',{drill:HP,labels:'out',u:'$'},{tag:'Drill',dm:true}),
  V('Legend at the bottom, rotated','Start angle moved and labels off for a minimal look.','Rotation: 90° · Legend › Position: Bottom','pie',{cats:CAT4,v:CAT4S,legend:'bottom',rot:90,u:'$'})
 ]},
{id:'donut',n:'Donut chart',cat:'part',st:'ga',ic:'donut',goals:['part','kpi'],
 best:'A pie with a hole: room for a total or label in the middle.',
 wells:[['Legend','Channel'],['Values','Σ Sales'],['Details',''],['Tooltips','']],uses:['Channel share of sales','Budget used vs remaining','Task status split'],avoid:'Precise comparisons of similar slices.',
 v:[
  V('Shares with a legend','Three channels with a side legend.','Legend: Channel','pie',{cats:CH,v:CHM.map(a=>sum0(a)),inner:.6,legend:'right',labels:'in',u:'$'}),
  V('Thin ring','A larger inner radius for a lighter ring.','Format › Slices › Inner radius: 78%','pie',{cats:CAT4,v:CAT4S,inner:.78,legend:'right',u:'$'}),
  V('Total in the center','A card placed over the hole shows the total.','Overlay a card visual, or use the card image technique','pie',{cats:CH,v:CHM.map(a=>sum0(a)),inner:.66,center:true,cl:'Sales',legend:'bottom',u:'$'},{tag:'Technique'}),
  V('Progress ring','Done vs remaining as two slices; remaining in a track color.','Values: Done, Remaining · color remaining gray','pie',{ring:['Done',72,'Remaining',28],inner:.74,center:'72%',cl:'Complete',sort:false},{tag:'Technique'}),
  V('Half donut','A hidden 50% slice and a rotation turn the donut into an arc.','Add a blank slice equal to the total · Rotation 270° · color it transparent','pie',{cats:CH,v:CHM.map(a=>sum0(a)),inner:.62,semi:true,center:true,cl:'Sales',u:'$'},{tag:'Technique'}),
  V('Detail labels outside','Name, value and share around the ring.','Detail labels › Label contents: All detail labels','pie',{cats:CAT4,v:CAT4S,inner:.58,labels:'detail',u:'$'}),
  V('Drill down: Category › Subcategory','Click a segment in drill mode to split it.','Legend: hierarchy · drill mode','pie',{drill:HP,inner:.6,labels:'out',u:'$'},{tag:'Drill',dm:true})
 ]},
{id:'treemap',n:'Treemap',cat:'part',st:'ga',ic:'treemap',goals:['part','compare'],
 best:'Nested rectangles sized by value. Many categories and hierarchy in a small space.',
 wells:[['Category','Category'],['Details','Subcategory'],['Values','Σ Sales'],['Tooltips','Margin %']],uses:['Sales by subcategory within category','Disk usage by folder','Portfolio exposure by sector'],avoid:'Comparing tiles of similar size, or values with negatives.',
 v:[
  V('Sales by subcategory','Sixteen subcategories in one view.','Category: Subcategory · Values: Sales','treemap',{cats:SUBS.map(s=>s.n),v:SUBS.map(s=>s.v[0]),u:'$'}),
  V('Grouped by category (Details)','Category groups, subcategories inside.','Category: Category · Details: Subcategory','treemap',{nest:true,u:'$'}),
  V('Color by margin','Size shows sales; color shows margin.','Format › Colors › fx › Gradient based on Margin %','treemap',{cats:SUBS.map(s=>s.n),v:SUBS.map(s=>s.v[0]),m:SUBS.map(s=>s.v[1]/s.v[0]*100),grad:true,u:'$'},{tag:'fx'}),
  V('Drill down: Category › Subcategory › Product','Click a tile in drill mode to open it.','Category: hierarchy · drill mode','treemap',{drill:HP,u:'$'},{tag:'Drill',dm:true}),
  V('Highlight a tile','Every tile but one in gray.','Colors › fx › Rules','treemap',{cats:SUBS.map(s=>s.n),v:SUBS.map(s=>s.v[0]),hl:2,u:'$'},{tag:'fx'})
 ]},

/* ======================= DISTRIBUTION / SCHEDULE ======================= */
{id:'scatter',n:'Scatter, bubble and dot plot',cat:'rel',st:'ga',ic:'scatter',goals:['rel','compare'],
 best:'Two measures per point to reveal correlation, clusters and outliers; size adds a third.',
 wells:[['Values','Store'],['X-axis','Σ Ad spend'],['Y-axis','Σ Revenue'],['Legend','Format'],['Size','Σ Customers'],['Play axis','Year'],['Tooltips','']],uses:['Ad spend vs revenue by store','Price vs margin by product','Plan vs actual by department'],avoid:'Few points; a bar chart reads faster.',
 v:[
  V('Spend vs revenue','Every store as a point.','Values: Store · X-axis: Ad spend · Y-axis: Revenue','scatter',{pts:STORES,xt:'Ad spend ($K)',yt:'Revenue ($K)',ux:'',uy:'',zeroX:1,zeroY:1}),
  V('Bubble chart','Bubble size adds customer count.','Size: Customers','scatter',{pts:STORES,size:true,xt:'Ad spend ($K)',yt:'Revenue ($K)',st:'Customers',groups:['Flagship','Mall','Outlet'],zeroX:1,zeroY:1}),
  V('Colored by category','Legend splits points by store format.','Legend: Format','scatter',{pts:STORES,groups:['Flagship','Mall','Outlet'],xt:'Ad spend ($K)',yt:'Revenue ($K)',zeroX:1,zeroY:1}),
  V('Quadrants','Average lines split the plot into four groups.','Analytics › X-axis constant line + Y-axis constant line (average)','scatter',{pts:STORES,quad:{x:'avg',y:'avg',names:['Efficient','Stars','Review','Over-spending']},xt:'Ad spend ($K)',yt:'Revenue ($K)'},{tag:'Analytics'}),
  V('Trend line','Least-squares line through the cloud.','Analytics › Trend line','scatter',{pts:STORES,trend:true,xt:'Ad spend ($K)',yt:'Revenue ($K)',zeroX:1,zeroY:1},{tag:'Analytics'}),
  V('Ratio line','Total Y over total X, drawn from the origin.','Analytics › Ratio line','scatter',{pts:STORES,ratio:true,xt:'Ad spend ($K)',yt:'Revenue ($K)',zeroX:1,zeroY:1},{tag:'Analytics'}),
  V('Symmetry shading','Plan on X, actual on Y; shading marks over and under plan.','Analytics › Symmetry shading','scatter',{pts:PVA,sym:true,labels:true,xt:'Plan ($K)',yt:'Actual ($K)'},{tag:'Analytics'}),
  V('Category labels','Each point named on the plot.','Format › Category label: On','scatter',{pts:PVA,labels:true,xt:'Plan ($K)',yt:'Actual ($K)'}),
  V('Dot plot','A categorical X-axis turns the scatter into a dot plot.','X-axis: Carrier (categorical) · Y-axis: Delivery days','scatter',{dot:DOTS,xt:'Carrier',yt:'Delivery days',uy:'d',zeroY:1}),
  V('Play axis','Press play to animate five years of market movement.','Play axis: Year · press ▶ in the visual','scatter',{play:PLAY,size:true,xt:'Sales growth (%)',yt:'Margin (%)',ux:'',uy:'',st:'Sales ($K)'},{tag:'Animation',play:true}),
  V('Zoom sliders and drag to zoom','Drag a rectangle to zoom both axes; reset from the header.','Format › X-axis and Y-axis › Zoom slider: On','scatter',{pts:STORES,size:true,groups:['Flagship','Mall','Outlet'],xt:'Ad spend ($K)',yt:'Revenue ($K)'},{tag:'Zoom',brush:true,zoom:'x'}),
  V('Logarithmic X-axis','Prices from $20 to $3,000 on one readable axis.','Format › X-axis › Scale type: Log','scatter',{pts:PRODPTS,logx:true,size:true,groups:['Bikes','Components','Clothing & accessories'],xt:'Avg price (log)',yt:'Margin %',ux:'$',uy:'%',us:'$',st:'Sales'}),
  V('Automatic clusters','Points grouped by the built-in clustering.','More options (…) › Automatically find clusters','scatter',{pts:STORESK,groups:['Cluster 1','Cluster 2','Cluster 3'],xt:'Ad spend ($K)',yt:'Revenue ($K)',zeroX:1,zeroY:1},{tag:'AI'})
 ]},
{id:'gantt',n:'Gantt',cat:'rel',st:'preview',ic:'gantt',goals:['trend','detail'],
 best:'Task durations, progress and milestones on a time axis, grouped by category.',
 wells:[['Task','Task name'],['Start','Start date'],['End','End date'],['Progress','% complete'],['Categories','Phase'],['Columns','Owner'],['Tooltips','']],uses:['Project plans by phase','Campaign calendars','Maintenance windows'],avoid:'More than 1,000 rows, the visual\'s limit.',
 v:[
  V('Project schedule','Phases with cascading color; progress shown on each bar.','Task, Start, End · Progress: % complete · Categories: Phase','gantt',{}),
  V('Progress as fill','Bordered bars filled to the completed share.','Format › Progress › Style: fill','gantt',{prog:'fill'}),
  V('Milestones and today','Diamonds for milestones (blank End) and a line for today.','End left blank for milestones · Format › Today line: On','gantt',{today:45},{tag:'Milestones'}),
  V('Colors by phase','More granular colors per category.','Rows › Color › More granular','gantt',{mode:'granular'}),
  V('Task detail columns','Owner and completion beside the task names.','Columns: Owner, % complete','gantt',{cols:['Owner','Done']}),
  V('Status colors','Conditional formatting: late, at risk, done.','Rows › Color › fx › Rules','gantt',{mode:'status',today:58},{tag:'fx'}),
  V('Days with weekend shading','Zoomed to days with Saturdays and Sundays shaded.','Axis › Primary level: Days · Shade days: Sat, Sun','gantt',{days:true,today:24}),
  V('Zoom the time axis','Drag across the timeline or use the slider to focus on weeks.','Zoom axis in the visual','gantt',{},{tag:'Zoom',zoom:true,brush:true,z:[.25,.7]})
 ]},

/* ======================= MAPS ======================= */
{id:'azure-maps',n:'Azure Maps',cat:'maps',st:'ga',ic:'azure',goals:['geo'],
 best:'The current built-in map: bubbles, heat, 3D columns, filled regions, paths, pies, clusters and reference layers.',
 wells:[['Location','City'],['Latitude',''],['Longitude',''],['Legend','Region'],['Size','Σ Sales'],['Tooltips','']],uses:['Store sales by city','Delivery density heat map','Shipping lanes from a distribution center'],avoid:'Tenants where admins have not enabled it, or report readers in unsupported regions.',
 v:[
  V('Bubble layer','Sales by city as sized bubbles. Drag to pan, use + and −.','Location: City · Size: Sales','wmap',{},{map:true}),
  V('Bubbles by category','Legend colors the bubbles by region.','Legend: Region','wmap',{byGroup:true},{map:true}),
  V('Heat map layer','Density of sales as a heat surface.','Format › Heat map layer: On · Bubble layer: Off','wmap',{layer:'heat',style:'dark'},{map:true}),
  V('3D column layer','Columns rise from each city on a tilted map.','Format › 3D column layer: On · tilt the map','usmap',{layer:'3d',fill:'none',pitch:.62,style:'gray'},{map:true}),
  V('Filled map layer','States shaded by sales.','Format › Filled map layer · Location: State','usmap',{fill:'seq'},{map:true}),
  V('Path layer','Shipping lanes from Amsterdam; width shows volume.','Path ID + point order fields · Format › Path layer','wmap',{layer:'path',style:'night'},{map:true}),
  V('Cluster bubbles','Nearby points merge. Click a cluster to zoom in.','Bubble layer › Cluster bubbles: On','wmap',{layer:'cluster'},{map:true,tag:'Zoom'}),
  V('Pie chart layer','A pie per city split by channel.','Legend: Channel · Format › Pie chart layer','wmap',{layer:'pie'},{map:true}),
  V('Reference layer','Custom sales territories uploaded as GeoJSON.','Format › Reference layer › upload GeoJSON','usmap',{fill:'ref'},{map:true}),
  V('Marker layer','Pin icons per category instead of bubbles.','Format › Marker layer · icon per category','wmap',{layer:'marker'},{map:true}),
  V('Drill down: Region › City (click to zoom)','Click a region in drill mode: the map zooms to it and splits into cities.','Location: Region › City hierarchy · Visual header ↓ · click a bubble','wmap',{layer:'drill'},{map:true,dm:true,tag:'Drill'}),
  V('Map style: night','Basemap styles include road, grayscale, dark, night and satellite.','Format › Map settings › Style: Night','wmap',{style:'night',byGroup:true},{map:true})
 ]},
{id:'map',n:'Map (Bing)',cat:'maps',st:'legacy',ic:'map',goals:['geo'],
 best:'The classic bubble map. Scheduled for deprecation; convert to Azure Maps where you can.',
 wells:[['Location','City'],['Legend',''],['Latitude',''],['Longitude',''],['Bubble size','Σ Sales'],['Tooltips','']],uses:['Sales by city','Customers by country','Stores by region with pie charts'],avoid:'New reports; use Azure Maps unless your readers are in China, Korea or a government cloud.',
 v:[
  V('Bubble map','Bubble size by sales.','Location: City · Bubble size: Sales','wmap',{style:'road'},{map:true}),
  V('Pie charts on the map','Add a Legend field and each bubble becomes a pie.','Legend: Channel','wmap',{layer:'pie',style:'road'},{map:true}),
  V('Heat map','The heat map option replaces bubbles with density.','Format › Heat map: On','wmap',{layer:'heat',style:'road'},{map:true}),
  V('Drill down: Region › City','Click a region in drill mode to zoom into its cities.','Location: hierarchy · drill mode','wmap',{layer:'drill',style:'road'},{map:true,dm:true,tag:'Drill'}),
  V('Colored by region','Bubble colors from a legend field.','Legend: Region','wmap',{byGroup:true,style:'road'},{map:true})
 ]},
{id:'filled-map',n:'Filled map (Bing)',cat:'maps',st:'legacy',ic:'filled',goals:['geo','compare'],
 best:'Choropleth shading of regions. Scheduled for deprecation along with the Bing map.',
 wells:[['Location','State'],['Legend',''],['Latitude',''],['Longitude',''],['Tooltips','']],uses:['Sales by state','Growth by country','Coverage by postcode'],avoid:'Raw totals that mostly reflect population; map a rate instead.',
 v:[
  V('Sequential shading','Darker states sell more.','Fill colors › fx › Gradient based on Sales','usmap',{fill:'seq'},{map:true,tag:'fx'}),
  V('Diverging growth','Red for decline, blue for growth, gray around zero.','fx › Gradient › Add a middle color','usmap',{fill:'div'},{map:true,tag:'fx'}),
  V('Rule buckets','Three bands with labels: declining, flat, growing.','fx › Rules','usmap',{fill:'rules'},{map:true,tag:'fx'}),
  V('Drill down: Region › State (click to zoom)','Click a region in drill mode; the map zooms and colors its states.','Location: Region › State · drill mode','usmap',{fill:'drill'},{map:true,dm:true,tag:'Drill'}),
  V('Colored by region','Categorical fill from a legend field.','Legend: Region','usmap',{fill:'region'},{map:true})
 ]},
{id:'shape-map',n:'Shape map',cat:'maps',st:'preview',ic:'shape',goals:['geo','compare'],
 best:'Color-coded regions from built-in or custom TopoJSON, including non-geographic shapes like floor plans.',
 wells:[['Location','State'],['Legend',''],['Color saturation','Σ Sales'],['Tooltips','']],uses:['Sales by state with equal-size tiles','Store floor traffic by zone','Seat or room utilization'],avoid:'Point locations; it colors areas only.',
 v:[
  V('Built-in US states','A built-in map shaded by sales.','Format › Map settings › Map type: USA: States','usmap',{fill:'seq',style:'canvas'},{map:true}),
  V('Hex tile map','Custom TopoJSON gives every state equal weight.','Map settings › Custom map › upload TopoJSON','hexmap',{}),
  V('Floor plan','Custom shapes for store zones colored by sales per m².','Custom map: floor plan TopoJSON · Location: Zone','floor',{}),
  V('Diverging tiles','Growth on the hex layout.','Color saturation: YoY % · diverging colors','hexmap',{metric:'g'},{tag:'fx'})
 ]},
{id:'arcgis',n:'ArcGIS for Power BI',cat:'maps',st:'ga',ic:'arcgis',goals:['geo','rel'],
 best:'Esri mapping with spatial analysis: heat, clustering, drive-time areas, demographics and infographics.',
 wells:[['Location','Store address'],['Size','Σ Sales'],['Color',''],['Time',''],['Tooltips','']],uses:['Catchment areas around stores','Demographic overlays','Site selection'],avoid:'Reports for readers without access to Esri content they need.',
 v:[
  V('Heat map','Light gray canvas with a heat layer.','Layers › Symbology › Heat map','usmap',{layer:'heat',fill:'none',style:'canvas'},{map:true}),
  V('Clustering','Stores grouped at small scales; click to zoom.','Symbology › Clustering','usmap',{layer:'cluster',fill:'none',style:'canvas'},{map:true,tag:'Zoom'}),
  V('Drive-time areas','10, 20 and 30-minute drive times around a store.','Analysis › Buffer / drive time','usmap',{layer:'drive',fill:'none',style:'canvas'},{map:true}),
  V('Infographics','Demographic cards beside the map.','Infographics › add demographic cards','usmap',{layer:'info',fill:'none',style:'canvas'},{map:true}),
  V('Smart mapping by amount','Color by amount with class breaks.','Symbology › Color by amount','usmap',{fill:'seq',style:'canvas'},{map:true})
 ]},

/* ======================= CARDS / KPI ======================= */
{id:'card',n:'Card',cat:'kpi',st:'ga',ic:'card',goals:['kpi'],
 best:'Key numbers with optional reference labels, images and categories. The card generally available since November 2025.',
 wells:[['Values','Σ Sales, Σ Profit'],['Categories',''],['Reference labels','Sales LY, Target'],['Tooltips','']],uses:['Headline totals across the top of a page','KPI tiles per channel or region','Metric with trend image and comparison'],avoid:'Using one card visual per number; one card can hold many values and loads faster.',
 v:[
  V('Single value','One number with its label.','Values: Sales','card',{n:1}),
  V('Multi-card','Several measures in one visual, in a grid.','Values: Sales, Profit, Orders, Return rate · Multi-card layout: grid','card',{n:4,cols:2}),
  V('Reference labels','Comparison to last year and target under each value.','Format › Reference labels › Add label · Detail','card',{n:2,refs:['ly','tg']}),
  V('Callout icons','A small image beside each value.','Format › Callout › Image: from data','card',{n:4,cols:2,icons:true}),
  V('Trend image','A data-driven SVG trend as the card image.','Format › Image › Image type: Select from data (SVG measure)','card',{n:2,img:true,refs:['ly']},{tag:'Technique'}),
  V('Cards by category','One section per channel from the Categories well.','Categories: Channel · Multi-category layout','card',{cats:true,refs:['ly']}),
  V('Conditional formatting','Cards below target switch to an alert style.','Format › Callout › Font color › fx · Card › Border › fx','card',{n:2,cf:true,refs:['tg'],img:true},{tag:'fx'}),
  V('Legacy card','The pre-November 2025 single card, kept for older reports.','Visualizations pane › … › Restore default visuals','card',{legacy:true},{tag:'Legacy'})
 ]},
{id:'multi-row-card',n:'Multi-row card',cat:'kpi',st:'legacy',ic:'mrow',goals:['kpi','detail'],
 best:'Rows of values per category. Kept for existing reports; the card visual replaces it.',
 wells:[['Fields','Region, Σ Sales, Σ Customers, vs LY']],uses:['Summary row per region','Key facts for a selected customer','Short record lists'],avoid:'New reports; the card visual with categories does the same job.',
 v:[
  V('Row per region','Category title with three values each.','Fields: Region, Sales, Customers, vs LY','mrow',{}),
  V('Accent bar','A colored bar on each row.','Format › Cards › Accent bar: On','mrow',{accent:true}),
  V('Measures only','No category, just a block of measures.','Fields: Sales, Profit, Orders, Margin','mrow',{measures:true}),
  V('Two-column layout','Narrow container wraps values into two columns.','Resize the visual','mrow',{two:true,accent:true})
 ]},
{id:'kpi',n:'KPI',cat:'kpi',st:'ga',ic:'kpi',goals:['kpi','trend'],
 best:'A value, its goal and the distance to goal, with a trend line behind.',
 wells:[['Value','Σ Sales'],['Trend axis','Month'],['Target','Sales goal']],uses:['Sales vs goal year to date','Return rate vs threshold','On-time delivery vs SLA'],avoid:'Measures without a goal; use a card.',
 v:[
  V('On track','Above goal: green status and trend.','Value: Sales · Trend axis: Month · Target: Goal','kpi',{i:0,date:true}),
  V('Behind goal','Below goal: red status with distance.','Same fields, different data','kpi',{i:1}),
  V('Lower is better','For costs and rates, direction is reversed.','Format › Indicator › Direction: Low is good','kpi',{i:2}),
  V('Indicator only','No trend axis; just value, goal and status.','Format › Trend axis: Off','kpi',{i:0,notrend:true}),
  V('Distance as an amount','Distance to goal in units instead of percent.','Format › Goals › Distance: Absolute','kpi',{i:1,abs:true}),
  V('KPI row','Four KPIs side by side.','Four KPI visuals, aligned','kpi',{row:true,notrend:false})
 ]},
{id:'gauge',n:'Gauge',cat:'kpi',st:'ga',ic:'gauge',goals:['kpi'],
 best:'A single value on a radial scale, with an optional target.',
 wells:[['Value','Σ Sales'],['Minimum value',''],['Maximum value','Sales max'],['Target value','Target'],['Tooltips','']],uses:['Sales against quota','Capacity utilization','Survey score out of 10'],avoid:'Comparing many values; a bar chart is more compact.',
 v:[
  V('Value vs target','Fill to the value, needle at the target.','Value: Sales · Target value: Target · Maximum value: Max','gauge',{g:{l:'Sales vs target',v:TYS,min:0,max:TYS*1.3,tgt:TYS*1.08,u:'$'}}),
  V('Percent of target','Scale from 0% to 150% with the target at 100%.','Value: % of target · Min 0 · Max 1.5 · Target 1','gauge',{g:{l:'% of target',v:.86,min:0,max:1.5,tgt:1},pct:true}),
  V('Conditional fill','Fill color follows rules on % of target.','Colors › Fill color › fx › Rules','gauge',{g:{l:'% of target',v:.78,min:0,max:1.2,tgt:1},pct:true,rule:true},{tag:'fx'}),
  V('Compact, no callout','Callout value off; the label stays.','Format › Callout value: Off','gauge',{g:{l:'Utilization',v:.64,min:0,max:1,tgt:.8},pct:true,callout:false}),
  V('Gauge strip','One gauge per region, same scale.','Four gauges with matching min, max and target','gauge',{strip:true,rule:true}),
  V('No target','Just the value against the axis.','Remove the Target value field','gauge',{g:{l:'Customer score',v:8.1,min:0,max:10,u:''},target:false})
 ]},
{id:'goals',n:'Goals (metrics)',cat:'kpi',st:'ga',ic:'goals',goals:['kpi','action'],
 best:'Scorecards of goals with owners, status, progress and check-ins, embedded in a report.',
 wells:[['Scorecard','Choose from the Goals / Metrics hub']],uses:['Quarterly OKRs','Team scorecards','Executive goal tracking'],avoid:'Metrics without owners or a cadence of check-ins.',
 v:[
  V('Scorecard list','Goals with owner, status, value and progress.','Insert the Goals visual · pick a scorecard','goals',{}),
  V('Single goal','One goal as a card with its trend.','Choose a single metric','goals',{single:true}),
  V('Roll-up with submetrics','Child goals roll up to the parent.','Scorecard › add submetrics','goals',{roll:true}),
  V('Check-in notes','The latest note from each owner.','Owners add check-ins with notes','goals',{notes:true})
 ]},

/* ======================= TABLES ======================= */
{id:'table',n:'Table',cat:'tables',st:'ga',ic:'table',goals:['detail','compare'],
 best:'Rows and columns of exact values, with conditional formatting and sparklines.',
 wells:[['Columns','Product, Σ Sales, Σ Units, Margin %, YoY %']],uses:['Product lists with exact figures','Transaction detail','Leaderboards with icons and bars'],avoid:'Trends and patterns that a chart would show at a glance.',
 v:[
  V('Default with totals','Exact values and a totals row. Click a header to sort.','Columns: Product, Sales, Units, Margin, YoY · Totals: On','table',{}),
  V('Background color scale','A heat map inside the Sales column.','Cell elements › Background color › fx › Gradient','table',{cf:'bg'},{tag:'fx'}),
  V('Data bars','In-cell bars scaled to the column.','Cell elements › Data bars: On','table',{cf:'bars'},{tag:'fx'}),
  V('Icons','Status icons beside year-over-year change.','Cell elements › Icons › Rules','table',{cf:'icons'},{tag:'fx'}),
  V('Font color rules','Negative growth in red, strong growth in green.','Cell elements › Font color › fx › Rules','table',{cf:'font'},{tag:'fx'}),
  V('Sparklines','A trend line for each product.','Columns › Sales › Add a sparkline (by Month)','table',{cf:'spark'}),
  V('Images and web URLs','Category icon and a product link column.','Data category: Image URL / Web URL · Values › URL icon','table',{cf:'img',cat:false}),
  V('Minimal style','Style preset without row lines.','Format › Style presets › Minimal','table',{style:'minimal'}),
  V('Alternating rows','Banded rows make wide tables easier to scan.','Style presets › Alternating rows','table',{style:'alt'}),
  V('Visual calculations','Running total and % of total computed on the visual.','New visual calculation: RUNNINGSUM([Sales]) · [Sales] / COLLAPSEALL([Sales], ROWS)','table',{cf:'calc'},{tag:'Visual calc'})
 ]},
{id:'matrix',n:'Matrix',cat:'tables',st:'ga',ic:'matrix',goals:['detail','compare'],
 best:'A pivot table: row and column hierarchies, subtotals, expand and collapse, conditional formatting.',
 wells:[['Rows','Region › Country'],['Columns','Quarter'],['Values','Σ Sales']],uses:['Sales by region and quarter','P&L by account hierarchy','Cohort tables'],avoid:'Very wide column sets; readers lose the row header.',
 v:[
  V('Expand and collapse rows','Click + or − beside a region; ⇓ expands all, ↑ collapses.','Rows: Region, Country · Row headers › +/- icons: On','matrix',{open:[0]},{tag:'Drill',matrix:true}),
  V('Cross-tab heat map','Background color scale across every cell.','Cell elements › Background color › fx › Gradient','matrix',{heat:true,open:[0,1]},{tag:'fx',matrix:true}),
  V('Tabular layout','Row headers in separate columns with subtotals.','Row headers › Layout: Tabular','matrix',{layout:'tabular'}),
  V('Values on rows','Measures listed down the rows under each region.','Values › Options › Switch values to rows','matrix',{vrows:true}),
  V('Sparklines','A quarterly trend per row.','Values › Sales › Add a sparkline','matrix',{spark:true,open:[1]},{matrix:true}),
  V('Data bars on totals','Bars in the total column.','Cell elements › Data bars (Total)','matrix',{bars:true,open:[0]},{tag:'fx',matrix:true}),
  V('Drill down on rows','Drill mode: click a region to show only its countries. ⇊ goes to the country level for everyone.','Visual header › Drill on: Rows · ↓ / ⇊ / ⇓','matrix',{},{tag:'Drill',matrix:true,dm:true})
 ]},

/* ======================= SLICERS ======================= */
{id:'slicer',n:'Slicer',cat:'filters',st:'ga',ic:'slicer',goals:['filter'],
 best:'The classic slicer: vertical list, tiles, dropdown, ranges and relative dates.',
 wells:[['Field','Region']],uses:['Region or channel filter','Date range for the page','Numeric range such as price'],avoid:'Dozens of slicers on one page; consider the Filters pane or Apply all.',
 v:[
  V('Vertical list','Multi-select checkboxes with Select all.','Slicer settings › Style: Vertical list · Show "Select all": On','slicer',{mode:'list',all:true,sel:[0,2]}),
  V('Dropdown','Saves space; opens on click.','Slicer settings › Style: Dropdown','slicer',{mode:'dropdown',sel:[1]}),
  V('Tile','Horizontal buttons that wrap.','Slicer settings › Style: Tile','slicer',{mode:'tile',items:CH,field:'Channel',sel:[0]}),
  V('Between (numeric range)','Two inputs and a range slider.','Field: Order amount · Style: Between','slicer',{mode:'between',field:'Order amount',min:20,max:4000,u:'$'}),
  V('Date range','Start and end dates with a slider.','Field: Order date · Style: Between','slicer',{mode:'date',field:'Order date',min:Date.UTC(2025,0,1),max:Date.UTC(2025,11,31)}),
  V('Relative date','Last N months that rolls forward on each load.','Style: Relative date · Last 3 Months (Calendar)','slicer',{mode:'relative',field:'Order date'}),
  V('Hierarchy','Year › Quarter in one slicer.','Field: Year, Quarter','slicer',{mode:'hier',field:'Date',sel:[10,11]}),
  V('Single select with search','Radio-style selection and a search box.','Selection › Single select: On · More options › Search','slicer',{mode:'single',search:true,items:CAT4,field:'Category',sel:[0]})
 ]},
{id:'button-slicer',n:'Button slicer',cat:'filters',st:'ga',ic:'bslicer',goals:['filter'],
 best:'Buttons in a grid with images, values and conditional formatting.',
 wells:[['Field','Region'],['Highlight label','Σ Sales'],['Tooltips','']],uses:['Region or channel buttons with totals','Product category tiles with icons','Status filters with colors'],avoid:'Long lists; use a list slicer.',
 v:[
  V('Button grid','Clean buttons in a 2 × 2 grid.','Field: Region · Multi-button layout: Grid','bslicer',{items:BSI,cols:2,sel:[0]}),
  V('Icons on buttons','An image per value.','Format › Image: from data','bslicer',{items:BSP,cols:2,sel:[0]}),
  V('Values on buttons','Sales under each name from the Highlight label well.','Highlight label: Sales','bslicer',{items:BSC,cols:3,val:true,sel:[1]}),
  V('Conditional formatting','Background follows growth.','Buttons › Background › Fill color › fx','bslicer',{items:BSP,cols:2,val:true,cf:true},{tag:'fx'}),
  V('Vertical list of buttons','One column, full width.','Multi-button layout: Vertical','bslicer',{items:BSC,cols:1,vert:true,val:true,sel:[0]}),
  V('Single select, forced','Exactly one button is always selected.','Slicer settings › Single select · Force selection','bslicer',{items:BSC,cols:3,single:true,force:true,sel:[2]})
 ]},
{id:'list-slicer',n:'List slicer',cat:'filters',st:'preview',ic:'lslicer',goals:['filter'],
 best:'A list with pictures, labels, hierarchy, search and a dropdown mode with selection pills.',
 wells:[['Values','Category'],['Tooltips','']],uses:['Category list with icons and totals','Two-level product hierarchy','Compact dropdown with pills'],avoid:'Fewer than five values; a button slicer is faster to scan.',
 v:[
  V('Pictures and labels','Icons and secondary labels beside each value.','Values: Category · Image and label from data','lslicer',{mode:'pics',sel:[0]}),
  V('Hierarchy','Expand categories to select subcategories.','Values: Category, Subcategory','lslicer',{mode:'hier',sel:[0,1]}),
  V('Dropdown with selection pills','Selected values become pills; a count pill shows the rest.','Slicer settings › Style: Dropdown','lslicer',{mode:'dropdown',sel:[0,1,3]}),
  V('Search','Type to narrow a long list.','More options › Search (Ctrl+F)','lslicer',{mode:'search'}),
  V('Conditional formatting','Item colors from a margin rule.','Buttons › Background › fx · Rules','lslicer',{mode:'cf'},{tag:'fx'}),
  V('Restrict to leaf nodes','Only subcategories can be selected.','Slicer settings › Restrict to leaf nodes: On','lslicer',{mode:'leaf',sel:[11]})
 ]},
{id:'input-slicer',n:'Input slicer',cat:'filters',st:'ga',ic:'islicer',goals:['filter','action'],
 best:'Free-text or numeric input with filter operators; also an input box for write-back flows.',
 wells:[['Field','Product name (optional)']],uses:['Search products by name fragments','Filter amounts with >500 or 100-200','Collect a comment for a translytical task flow'],avoid:'Picking from a short known list; use a button slicer.',
 v:[
  V('Contains any','Typed values become pills that filter the page.','Field: Product · Operator: Contains any','islicer',{pills:['road','e-bike'],op:0}),
  V('Filter operators','Seven operators from contains to exact match.','Operator dropdown on the visual','islicer',{pills:['helmet'],op:3,showOp:true},{st:{oo:true}}),
  V('Numeric expressions','Ranges and comparisons such as >500 or 100-200.','Field: Order amount (numeric)','islicer',{pills:['>500','100-200'],num:true,field:'Order amount'}),
  V('Input for write-back','No field: the slicer collects text for a data function button.','Leave Field empty · pair with a Data function button','islicer',{mode:'ttf'},{tag:'Write-back'})
 ]},

/* ======================= AI ======================= */
{id:'key-influencers',n:'Key influencers',cat:'ai',st:'ga',ic:'keyinf',goals:['ai','rel'],
 best:'Ranks the factors that drive a metric up, down, or to a category, and finds high-likelihood segments.',
 wells:[['Analyze','Churn'],['Explain by','Contract, Tenure, Tickets, Plan, Region'],['Expand by','']],uses:['What drives churn','What increases order value','Which factors lower satisfaction'],avoid:'Small samples; the model needs enough rows per factor.',
 v:[
  V('Categorical: drivers of churn','Pick a factor to see its effect against everyone else.','Analyze: Churn (Yes/No) · Explain by: factors','keyinf',{}),
  V('Continuous: order value','What makes the average increase.','Analyze: Order value (numeric)','keyinf',{cont:true}),
  V('Top segments','Clusters of customers with the highest churn.','Top segments tab','keyinf',{tab:'seg'}),
  V('Factor detail','A selected factor compared with the average.','Select a factor in the left pane','keyinf',{},{st:{f:2}})
 ]},
{id:'decomposition-tree',n:'Decomposition tree',cat:'ai',st:'ga',ic:'decomp',goals:['ai','change','detail'],
 best:'Drill a measure through any dimensions in any order; AI splits can pick the next level for you.',
 wells:[['Analyze','Σ Sales'],['Explain by','Region, Country, City']],uses:['Root-cause analysis of a sales drop','Cost breakdown by account and vendor','Where defects concentrate'],avoid:'Deep trees with many small nodes; lock levels you always need.',
 v:[
  V('Manual drill path','Click any node to expand the next level.','Select + on a node and pick a dimension','decomp',{sel:[0]},{tag:'Drill'}),
  V('AI split: high value','The tree follows the highest values automatically.','Select + › High value','decomp',{ai:'high',sel:[]},{tag:'AI'}),
  V('AI split: low value','Follows the lowest values to find weak spots.','Select + › Low value','decomp',{ai:'low',sel:[]},{tag:'AI'}),
  V('Relative analysis','AI split ranks by growth versus last year, not by size.','Format › Analysis › Type: Relative','decomp',{ai:'high',rel:true,sel:[]},{tag:'AI'})
 ]},
{id:'narrative',n:'Narrative (smart narrative)',cat:'ai',st:'ga',ic:'narr',goals:['ai'],
 best:'Text that summarizes the page or a visual, with dynamic values that update with filters.',
 wells:[['Inserted with','Insert › Narrative, or right-click a visual › Summarize']],uses:['Executive summary above a dashboard','Explaining a trend beside its chart','Copilot-written page summaries'],avoid:'Replacing the visuals; narrative works best beside them.',
 v:[
  V('Automatic summary','Generated from the visuals on the page.','Insert › Smart narrative','narr',{}),
  V('Custom text with dynamic values','Your sentences with measures that update.','Type text · + Value to insert a measure','narr',{mode:'custom'}),
  V('Copilot summary','Bullet summary written by Copilot.','Narrative › Copilot · prompt: Give an executive summary','narr',{mode:'copilot'},{tag:'Copilot'}),
  V('Summarize one visual','Narrative tied to a single chart.','Right-click a visual › Summarize','narr',{mode:'visual'})
 ]},
{id:'qna',n:'Q&A',cat:'ai',st:'retiring',ic:'qna',goals:['ai'],
 best:'Ask questions in plain language and get a visual back. Retires in December 2026; move to Copilot.',
 wells:[['Question','Typed by the reader']],uses:['Self-service questions on a dashboard','Exploring a model with synonyms','Prototyping visuals quickly'],avoid:'New reports; existing Q&A visuals stop working after the retirement.',
 v:[
  V('Ask a question','Pick a suggested question to see the result.','Insert › Q&A · type a question','qna',{q:0}),
  V('Name the visual type','Ending with "as line chart" picks the visual.','Add "as column chart" or "as line chart" to the question','qna',{q:1}),
  V('Turn into a standard visual','Convert the answer into a normal visual on the page.','Q&A header › Turn this Q&A result into a standard visual','qna',{q:2,convert:true}),
  V('Migration path','Where each Q&A experience moves.','Replace with Copilot · use Prep data for AI for synonyms','qna',{mode:'retire'},{tag:'Retiring'})
 ]},

/* ======================= EMBEDS ======================= */
{id:'paginated-report',n:'Paginated report visual',cat:'embed',st:'ga',ic:'pag',goals:['detail','action'],
 best:'A pixel-perfect, multi-page report inside the page, driven by report filters and exportable.',
 wells:[['Parameters','Region, Year (mapped from fields)']],uses:['Invoices and statements','Printable lists that span pages','Regulatory reports with fixed layout'],avoid:'Interactive exploration; use native visuals.',
 v:[
  V('Invoice-style page','Fixed layout with header, lines and total.','Insert › Paginated report · Connect to report','pag',{}),
  V('Parameters from filters','Report fields feed the paginated report parameters.','Format › Parameters › map to fields','pag',{mode:'params'}),
  V('Export formats','Readers export to PDF, Excel, Word and more.','Toolbar › Export','pag',{exp:true}),
  V('Grouped detail','Multi-page detail grouped by region with subtotals.','Paginated report with grouping','pag',{mode:'group'})
 ]},
{id:'power-apps',n:'Power Apps visual',cat:'embed',st:'ga',ic:'papps',goals:['action'],
 best:'An embedded app that receives report context, for write-back and actions.',
 wells:[['Power Apps data','Account, Region']],uses:['Log follow-ups next to the numbers','Approve requests in context','Edit a record you are looking at'],avoid:'Large data volumes passed to the app; the visual passes up to 1,000 records.',
 v:[
  V('Write-back form','Save a follow-up without leaving the report.','Power Apps data: fields · Choose app or create new','papps',{}),
  V('Record gallery','A list of records filtered by the report.','App gallery bound to the report context','papps',{mode:'gallery'}),
  V('Approval in context','Approve or reject with filter context shown.','Pass filter context to the app','papps',{mode:'approve'})
 ]},
{id:'power-automate',n:'Power Automate visual',cat:'embed',st:'ga',ic:'pauto',goals:['action'],
 best:'A button that runs a flow with the data the reader has filtered.',
 wells:[['Power Automate data','Region, Product']],uses:['Email the filtered rows to managers','Post an alert to a Teams chat','Create tasks for selected accounts'],avoid:'Publish to web; the visual needs signed-in users.',
 v:[
  V('Run-flow button','Readers click to start the flow.','Insert › Power Automate · Edit flow','pauto',{}),
  V('Flow with data context','The flow receives the filtered fields.','Power BI button clicked trigger · Send an email · Post message','pauto',{mode:'flow'}),
  V('Run status','Feedback after the flow runs.','Button text and loading states in Format','pauto',{mode:'status'})
 ]},
{id:'r-visual',n:'R script visual',cat:'embed',st:'ga',ic:'rviz',goals:['rel','detail'],
 best:'Any chart R can draw, rendered as an image from a dataset data frame.',
 wells:[['Values','Fields become the dataset data frame']],uses:['Statistical plots (box, density, regression)','Correlation matrices','Custom ggplot2 styles'],avoid:'Interactive cross-filtering from the plot itself; it is an image.',
 v:[
  V('Box plot (ggplot2)','Margin spread by category.','Insert › R script visual · ggplot2 code','rpy',{mode:'box'}),
  V('Density by group','Delivery-day distributions per carrier.','geom_density()','rpy',{mode:'density'}),
  V('Correlation matrix','corrplot of five measures.','library(corrplot)','rpy',{mode:'corr'}),
  V('Faceted regression','Spend vs revenue split by store format.','facet_wrap() + geom_smooth()','rpy',{mode:'facet'})
 ]},
{id:'python-visual',n:'Python visual',cat:'embed',st:'ga',ic:'pyviz',goals:['rel','detail'],
 best:'matplotlib or seaborn output from a pandas dataset DataFrame.',
 wells:[['Values','Fields become the dataset DataFrame']],uses:['Violin and distribution plots','Regression with confidence intervals','Heat maps of hour by weekday'],avoid:'Visuals that must cross-filter others; output is static.',
 v:[
  V('Violin plot','Order value distribution by channel.','sns.violinplot()','rpy',{mode:'violin'}),
  V('Regression with CI','Trend and 95% interval.','sns.regplot()','rpy',{mode:'reg'}),
  V('Heat map','Orders by weekday and hour.','sns.heatmap()','rpy',{mode:'heat'}),
  V('Scatter matrix','Pairwise view of three measures.','pandas.plotting.scatter_matrix()','rpy',{mode:'pair'})
 ]},

/* ======================= ELEMENTS ======================= */
{id:'image',n:'Image visual',cat:'elements',st:'ga',ic:'image',goals:['detail'],
 best:'Static or data-bound images, from uploads, URLs, OneLake files or fields.',
 wells:[['Image','Upload, URL or field']],uses:['Brand header','Product photo for the selected item','SVG measures as micro-charts'],avoid:'Images that carry numbers readers need; screen readers cannot read them.',
 v:[
  V('Static image','A header graphic.','Insert › Image','image',{mode:'static'}),
  V('Dynamic image from data','The image follows the selected product.','Image source: field with data category Image URL','image',{}),
  V('Image with an action','Clicking the image navigates.','Format › Action: Page navigation','image',{mode:'action'}),
  V('SVG from a measure','A DAX measure returns an SVG chart.','Measure → data category Image URL','image',{mode:'svg'},{tag:'Technique'})
 ]},
{id:'buttons',n:'Buttons and navigators',cat:'elements',st:'ga',ic:'btns',goals:['action','filter'],
 best:'Buttons with actions, page and bookmark navigators, slicer apply/clear and data function buttons.',
 wells:[['Action','Page navigation, Bookmark, Drill through, Web URL, Data function…']],uses:['Tab-like page navigation','Switch between bookmarked views','Apply many slicers at once'],avoid:'Hiding important content behind buttons.',
 v:[
  V('Button states','Default, hover, press and disabled styles.','Format › Button style › State','btns',{mode:'states'}),
  V('Page navigator','One button per page, kept in sync.','Insert › Buttons › Navigator › Page navigator','btns',{}),
  V('Bookmark navigator','Switch between saved views.','Insert › Buttons › Navigator › Bookmark navigator','btns',{mode:'bookmark'}),
  V('Apply all / Clear all slicers','Batch slicer changes into one query.','Insert › Buttons › Apply all slicers / Clear all slicers','btns',{mode:'slicers'}),
  V('Data function button','Runs a user data function for write-back.','Action: Data function · inputs from an input slicer','btns',{mode:'ttf'},{tag:'Write-back'})
 ]},
{id:'text-shapes',n:'Text box and shapes',cat:'elements',st:'ga',ic:'texts',goals:['detail'],
 best:'Titles, dynamic text, panels, arrows and callouts that structure a page.',
 wells:[['Text','Static or bound to measures']],uses:['Page titles with dynamic dates','Background panels grouping visuals','Arrows and annotations'],avoid:'Long text paragraphs that belong in a document.',
 v:[
  V('Dynamic text','Text with measure values inside.','Insert › Text box · + Value','texts',{}),
  V('Shapes as panels','Rounded rectangles, ovals, arrows and triangles.','Insert › Shapes','texts',{mode:'shapes'}),
  V('Annotation callout','A note pointing at a data point.','Text box + shape over a chart','texts',{mode:'callout'}),
  V('Header banner','Title, context and key numbers in one band.','Shape + text boxes + card','texts',{mode:'banner'})
 ]}
];
