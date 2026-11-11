/* ---------------- D2D Relay: buying credits online with Razorpay (app/payments.py, item 23): Buy credits, the
   Organisation page's Payments, and the admin portal's Payments (#/payments: the keys, what is on sale, every payment).
   The amount is always the server's; Razorpay's own window takes the card or UPI details, and the server checks the
   payment with Razorpay before any credits are added. Where the person is decides the currency (item 24, the server's
   rule): rupees only in India, US dollars everywhere else once PASDACS sets dollar prices. ---------------- */

/* an amount in the currency's smallest unit: ₹1,17,882 (Indian grouping) or $1,250; the minor part when there is one,
   or when asked */
const money = (minor, cur = 'INR', dec) => (Number(minor || 0) / 100).toLocaleString(cur === 'INR' ? 'en-IN' : 'en-US',
  {style: 'currency', currency: cur, minimumFractionDigits: dec || Number(minor || 0) % 100 ? 2 : 0, maximumFractionDigits: 2});
const rupees = (paise, dec) => money(paise, 'INR', dec);
const PAY_METHODS = {card: 'Card', upi: 'UPI', netbanking: 'Netbanking', wallet: 'Wallet', emi: 'EMI', paylater: 'Pay later'};

/* Razorpay's checkout script, loaded the first time someone pays */
let RZP_LOAD = null;
function loadCheckout() {
  if (window.Razorpay) return Promise.resolve();
  if (RZP_LOAD) return RZP_LOAD;
  RZP_LOAD = new Promise((resolve, reject) => {
    const s = document.createElement('script');
    const fail = why => { clearTimeout(t); RZP_LOAD = null; s.remove(); reject(new Error(why)); };
    const t = setTimeout(() => fail('timeout'), 20000);
    s.src = 'https://checkout.razorpay.com/v1/checkout.js';
    s.async = true;
    s.onload = () => { if (window.Razorpay) { clearTimeout(t); resolve(); } else fail('no Razorpay'); };
    s.onerror = () => fail('blocked');
    document.head.append(s);
  });
  return RZP_LOAD;
}
/* the app's accent as #rrggbb, for Razorpay's window */
function payAccent() {
  try {
    const c = document.createElement('canvas').getContext('2d');
    c.fillStyle = '#2563eb';
    c.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#2563eb';
    return /^#[0-9a-f]{6}$/i.test(c.fillStyle) ? c.fillStyle : '#2563eb';
  } catch (e) { return '#2563eb'; }
}
/* a POST whose status matters (the answer may be "not confirmed yet": try again) */
async function payPost(path, body) {
  const r = await fetch(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  if (r.status === 401) { toSignIn(); throw new Error('Signed out'); }
  let j = {};
  try { j = await r.json(); } catch (e) { /* not JSON */ }
  return {status: r.status, data: j, error: r.ok ? '' : (Array.isArray(j.detail) ? j.detail.map(d => d.msg).join('; ') : j.detail || `${r.status} ${r.statusText}`)};
}

/* ---------------- Buy credits ---------------- */
async function buyDialog(reason) {
  const o = ORG();
  if (!o.id) return;
  let d;
  try { d = await api('/api/payments'); } catch (e) { return requestDialog(reason); }
  if (!d.on || !(d.packs || []).length) return requestDialog(reason);
  const cur = d.currency || 'INR';                    // the server's: rupees only in India, US dollars everywhere else
  const list = d.packs.filter(p => (p.currency || 'INR') === cur);
  if (!list.length) return requestDialog(reason);
  let pick = list[Math.min(1, list.length - 1)], ord = null;
  const out = h('div', {role: 'status', 'aria-live': 'polite'});
  const payBtn = h('button', {class: 'btn primary', type: 'button'});
  const payLabel = () => payBtn.replaceChildren(icon('lock'), `Pay ${money(pick.amount, cur)}`);
  const cards = h('div', {class: 'packs', role: 'radiogroup', 'aria-label': 'Credit packs'}, list.map(p =>
    h('button', {type: 'button', class: 'pack' + (p === pick ? ' on' : ''), role: 'radio', 'aria-checked': String(p === pick), onclick: () => {
      pick = p;
      [...cards.children].forEach((c, i) => { const on = list[i] === p; c.classList.toggle('on', on); c.setAttribute('aria-checked', String(on)); });
      payLabel();
    }},
    h('b', {class: 'pcred'}, Number(p.credits).toLocaleString('en-IN')), h('span', {class: 'small muted'}, 'credits'),
    h('span', {class: 'pprice'}, money(p.price, cur)), p.gst ? h('span', {class: 'small muted'}, `+ ${money(p.gst, cur, true)} GST`) : null,
    h('span', {class: 'small faint'}, `${money(Math.round(p.amount / p.credits), cur, true)} a credit`))));
  const words = [cur === 'INR' && d.gst ? `GST of ${d.gst}% is added to each price.` : '', d.note || ''].filter(Boolean).join(' ');
  payLabel();
  const done = h('button', {class: 'btn primary', type: 'button', onclick: () => m.remove()}, icon('check'), 'Done');
  const paid = async (resp, ord) => {                 // Razorpay says paid: the server checks it, then adds the credits
    out.replaceChildren(h('div', {class: 'note'}, 'Paid. Checking the payment with Razorpay…'));
    for (let i = 0; i < 5; i++) {
      const r = await payPost('/api/payments/verify', resp).catch(e => ({status: 0, error: e.message}));
      if (r.status === 200) {
        await refreshOrg(true);
        bal.textContent = balance(r.data.credits);
        out.replaceChildren(h('div', {class: 'note ok'}, h('b', {}, `${Number(r.data.added).toLocaleString('en-IN')} credits added. `),
          `${r.data.org} now has ${credits(r.data.credits)}. `, h('a', {href: `/api/payments/${encodeURIComponent(ord.id)}/receipt`, target: '_blank', rel: 'noopener',
            style: 'text-decoration:underline'}, 'Open the receipt'), ' (it is emailed to you too).'));
        payBtn.replaceWith(done);
        done.focus();
        if (location.hash === '#/org') renderOrg();
        return;
      }
      if (r.status !== 503 && r.status !== 0) { out.replaceChildren(h('div', {class: 'note err'}, r.error)); payBtn.disabled = false; return; }
      await new Promise(res => setTimeout(res, 4000));
    }
    out.replaceChildren(h('div', {class: 'note warn'}, 'Razorpay has not confirmed the payment yet. The credits appear on their own as soon as it does (usually within a few minutes); you can close this.'));
    payBtn.replaceWith(done);
  };
  payBtn.onclick = async () => {
    payBtn.disabled = true;
    out.replaceChildren(h('div', {class: 'note'}, 'Opening Razorpay…'));
    try { await loadCheckout(); } catch (e) {
      payBtn.disabled = false;
      return out.replaceChildren(h('div', {class: 'note err'}, "Razorpay's payment window could not load. Check your internet connection; if an ad or script blocker is on, allow checkout.razorpay.com. Then try again."));
    }
    if (!ord || ord.pack !== pick.id) {               // Pay again on the same pack: the same order (Razorpay takes retries on it)
      try { ord = {...await api('/api/payments/order', {json: {pack: pick.id}}), pack: pick.id}; } catch (e) {
        payBtn.disabled = false;
        return out.replaceChildren(h('div', {class: 'note err'}, e.message));
      }
    }
    let settled = false, failed = '';
    const rzp = new window.Razorpay({
      key: ord.key, amount: ord.amount, currency: ord.currency, name: ord.name, description: ord.description, order_id: ord.order_id,
      prefill: ord.prefill, notes: {d2d_payment: ord.id}, theme: {color: payAccent()},
      modal: {ondismiss: () => {
        if (settled) return;
        payBtn.disabled = false;
        out.replaceChildren(failed ? h('div', {class: 'note err'}, `The payment did not go through: ${failed}. You can try again.`)
          : h('div', {class: 'note warn'}, 'The payment window was closed. Nothing was charged unless you finished paying; if you did, the credits appear here within a few minutes.'));
      }},
      handler: resp => { settled = true; paid(resp, ord); },
    });
    rzp.on('payment.failed', r => {
      failed = ((r && r.error) || {}).description || 'it was declined';
      out.replaceChildren(h('div', {class: 'note err'}, `The payment did not go through: ${failed}. Try again in the Razorpay window, or close it.`));
    });
    rzp.open();
    out.replaceChildren(h('div', {class: 'note'}, 'Finish paying in the Razorpay window.'));
  };
  const costs = costLine(), balance = n => `${d.org} has ${credits(n)}. ${costs.charAt(0).toUpperCase() + costs.slice(1)}.`;
  const bal = h('p', {style: 'margin-top:0'}, balance(d.credits));
  const m = modal('Buy credits', h('div', {class: 'mbody'},
    reason ? h('div', {class: 'note warn', style: 'margin-top:0'}, reason) : null,
    d.test ? h('div', {class: 'note warn', style: reason ? null : 'margin-top:0'}, h('b', {}, 'Test mode: no money moves. '),
      'Pay with one of the test cards in Razorpay’s documentation (an international one for US dollars).') : null,
    bal,
    d.can ? null : h('div', {class: 'note'}, d.why),
    cards,
    words ? h('div', {class: 'hint'}, words) : null,
    out,
    h('div', {class: 'row', style: 'justify-content:space-between;gap:12px;margin-top:12px;align-items:center;flex-wrap:wrap'},
      h('span', {class: 'small muted'}, cur === 'INR' ? 'Card, UPI, netbanking or wallet, through Razorpay. ' : 'By card, through Razorpay. ',
        h('a', {href: '#', onclick: e => { e.preventDefault(); m.remove(); requestDialog(reason); }}, 'Ask PASDACS instead')),
      d.can ? payBtn : null)));
}

/* a payment's state, in words */
function payState(p) {
  if (p.status === 'paid') return p.refunded ? h('span', {class: 'tag warn'}, `Paid · ${money(p.refunded, p.currency, true)} refunded`) : h('span', {class: 'tag ok'}, 'Paid');
  if (p.status === 'refunded') return h('span', {class: 'tag'}, 'Refunded');
  if (p.status === 'failed') return h('span', {class: 'tag err', title: p.error || ''}, 'Failed');
  return Date.now() / 1000 - p.created < 1800 ? h('span', {class: 'tag warn'}, 'Waiting') : h('span', {class: 'small muted'}, 'Not completed');
}

/* ---------------- the Organisation page's Payments (filled in after the page shows) ---------------- */
async function fillPayments(box) {
  let d;
  try { d = await api('/api/payments'); } catch (e) { return; }
  if (!box.isConnected || (!d.payments.length && !d.on)) return;
  const th = (cols, left) => h('thead', {}, h('tr', {}, cols.map((c, i) => h('th', {class: i < left ? 'l' : null}, c))));
  box.replaceChildren(h('div', {class: 'card'}, h('h3', {}, 'Payments'),
    h('div', {class: 'muted small', style: 'margin:-6px 0 8px'}, d.all ? `Credits bought online for ${d.org}. Receipts open in a new tab, to print or save.`
      : 'Credits you bought online. Receipts open in a new tab, to print or save.'),
    d.payments.length ? h('div', {class: 'orgwrap'}, h('table', {class: 'utable'}, th(['When', 'Who', 'Credits', 'Amount', 'Status', ''], 2),
      h('tbody', {}, d.payments.map(p => h('tr', {},
        h('td', {}, when(p.paid || p.created), p.live ? null : h('span', {class: 'tag', style: 'margin-left:6px'}, 'Test')),
        h('td', {}, p.user_name || '—'), h('td', {class: 'n'}, '+' + Number(p.credits).toLocaleString('en-IN')),
        h('td', {class: 'n'}, money(p.amount, p.currency, true)), h('td', {}, payState(p), p.method ? h('span', {class: 'small muted'}, ` ${PAY_METHODS[p.method] || p.method}`) : null),
        h('td', {class: 'n'}, p.status === 'paid' || p.status === 'refunded'
          ? h('a', {href: `/api/payments/${encodeURIComponent(p.id)}/receipt`, target: '_blank', rel: 'noopener'}, 'Receipt') : null))))))
      : h('div', {class: 'muted small'}, d.can ? 'None yet. Buy credits pays online, by card, UPI or netbanking.' : 'None yet.')));
}

/* ---------------- Payments (#/payments, the admin portal) ---------------- */
async function renderPayments() {
  const page = h('div', {class: 'page wide'});
  $('#main').replaceChildren(page);
  document.title = 'Payments · D2D Relay admin';
  let d;
  try { d = await api('/api/admin/payments'); } catch (e) { return page.append(h('div', {class: 'note err'}, e.message)); }
  if (location.hash !== '#/payments') return;
  const s = d.settings, th = (cols, left) => h('thead', {}, h('tr', {}, cols.map((c, i) => h('th', {class: i < left ? 'l' : null}, c))));
  const modeTag = d.mode === 'live' ? h('span', {class: 'tag ok'}, 'Live keys') : d.mode === 'test' ? h('span', {class: 'tag warn'}, 'Test keys')
    : h('span', {class: 'tag err'}, 'No keys');
  const copyBtn = text => h('button', {class: 'btn sm ghost', type: 'button', title: 'Copy', onclick: async () => {
    try { await navigator.clipboard.writeText(text); notify('Copied', 'ok'); } catch (e) { notify(text); } }}, icon('copy'));
  const keys = h('div', {class: 'card'}, h('h3', {}, 'Razorpay ', modeTag),
    h('dl', {class: 'kv small'},
      h('dt', {}, 'Key id'), h('dd', {}, d.key_id || h('span', {class: 'muted'}, 'not set')),
      h('dt', {}, 'Key secret'), h('dd', {}, d.key_secret ? 'set' : h('span', {class: 'tag err'}, 'not set')),
      h('dt', {}, 'Webhook secret'), h('dd', {}, d.webhook_secret ? 'set' : h('span', {class: 'tag warn'}, 'not set')),
      h('dt', {}, 'Webhook URL'), h('dd', {}, h('code', {}, d.webhook_url), ' ', copyBtn(d.webhook_url)),
      h('dt', {}, 'Webhook events'), h('dd', {}, d.events.join(', '))),
    h('p', {class: 'small muted'}, d.mode === 'test'
      ? `Test keys move no money, so ${d.test_for === 'all' ? 'every organisation can buy (a test install)' : 'only PASDACS’s own workspace can buy: sign in to the public site as info@pasdacs.com to try it end to end'}. Live keys open selling to everyone once it is switched on below.`
      : d.mode === 'live' ? 'Live keys: real payments. Organisations can buy once selling is switched on below.'
      : 'The keys go in .env (RELAY_RAZORPAY_KEY_ID, RELAY_RAZORPAY_KEY_SECRET, RELAY_RAZORPAY_WEBHOOK_SECRET); a restart picks them up.'),
    h('p', {class: 'small muted'}, 'In the Razorpay Dashboard, add a webhook (Account & Settings › Webhooks) with the URL above, the same secret and these events. '
      + 'Refunds are made there too; they show up here, and the credits are taken back by hand on Organisations if that is the rule.'));

  // what is on sale
  const on = h('input', {type: 'checkbox', checked: !!s.on});
  let who = s.who || 'owners';
  const whoSeg = h('div', {class: 'segbtn', role: 'group', 'aria-label': 'Who can buy'}, [['owners', 'Owners'], ['everyone', 'Everyone']].map(([v, label]) =>
    h('button', {type: 'button', class: v === who ? 'on' : '', 'aria-pressed': String(v === who), onclick: e => {
      who = v;
      [...whoSeg.children].forEach(b => { b.classList.toggle('on', b === e.currentTarget); b.setAttribute('aria-pressed', String(b === e.currentTarget)); });
    }}, label)));
  const gst = h('input', {type: 'number', class: 'num', min: 0, max: 28, step: 0.01, value: s.gst || 0, style: 'max-width:110px', 'aria-label': 'GST added, in per cent'});
  const note = h('input', {type: 'text', maxlength: 200, value: s.note || '', placeholder: 'Optional, under the prices: e.g. Prices include GST. Credits never expire.'});
  const rows = h('div', {class: 'packrows'});
  const addRow = (credits = '', price = '', usd = '') => {
    const c = h('input', {type: 'number', min: 1, step: 1, value: credits, placeholder: 'Credits', 'aria-label': 'Credits'});
    const p = h('input', {type: 'number', min: 1, step: 1, value: price, placeholder: 'Price in ₹', 'aria-label': 'Price in rupees'});
    const u = h('input', {type: 'number', min: 1, step: 1, value: usd || '', placeholder: 'Price in $', 'aria-label': 'Price in US dollars'});
    const r = h('div', {class: 'packrow'}, c, h('span', {class: 'small muted'}, 'credits'), h('span', {class: 'small muted'}, '₹'), p,
      h('span', {class: 'small muted'}, '$'), u,
      h('button', {class: 'btn sm ghost', type: 'button', title: 'Remove this pack', onclick: () => r.remove()}, icon('x')));
    rows.append(r);
  };
  (s.packs || []).forEach(p => addRow(p.credits, p.price, p.usd));
  if (!(s.packs || []).length) addRow();
  const err = h('div', {class: 'err-msg', role: 'alert'});
  const save = h('button', {class: 'btn primary', type: 'button'}, icon('check'), 'Save');
  save.onclick = async () => {
    const packs = [...rows.children].map(r => { const [c, p, u] = r.querySelectorAll('input');
      return {credits: parseInt(c.value, 10), price: parseInt(p.value, 10), usd: parseInt(u.value, 10) || 0}; })
      .filter(p => p.credits || p.price || p.usd);
    if (packs.some(p => !(p.credits > 0) || !(p.price > 0))) { err.textContent = 'Each pack needs a number of credits and a price in whole rupees.'; return; }
    save.disabled = true;
    try {
      await api('/api/admin/payments/settings', {method: 'PUT', json: {on: on.checked, who, gst: parseFloat(gst.value) || 0, note: note.value, packs}});
      notify('Saved', 'ok');
      renderPayments();
    } catch (e) { save.disabled = false; err.textContent = e.message; }
  };
  const selling = h('div', {class: 'card'}, h('h3', {}, 'What is on sale'),
    h('label', {class: 'chk'}, on, h('span', {}, h('b', {}, 'Sell credits online'), d.mode === 'live' ? '' : ' (with live keys; test keys let only PASDACS buy)')),
    h('label', {class: 'f'}, 'Who can buy'), whoSeg,
    h('div', {class: 'hint'}, 'Owners: each organisation’s owners; members ask them, or ask PASDACS. Everyone: anyone in the organisation.'),
    h('label', {class: 'f'}, 'Packs ', h('small', {}, 'up to 6; prices in whole rupees and, if wanted, whole US dollars')), rows,
    h('div', {class: 'hint'}, 'Where the buyer is decides: rupees only in India, US dollars everywhere else, also where Cloudflare '
      + 'cannot tell the country. A pack without a dollar price is not sold outside India; with no dollar prices at all, everyone pays '
      + 'in rupees. With live keys, dollars need Razorpay’s international payments switched on.'),
    h('button', {class: 'btn sm', type: 'button', style: 'margin-top:8px', onclick: () => { if (rows.children.length < 6) addRow(); }}, icon('plus'), 'Add a pack'),
    h('label', {class: 'f'}, 'GST added on top of rupee prices ', h('small', {}, 'per cent; 0: none added, the price is what people pay')), gst,
    h('label', {class: 'f'}, 'Note under the rupee prices ', h('small', {}, 'optional; shown to buyers in India')), note,
    err, h('div', {class: 'row', style: 'justify-content:space-between;margin-top:12px;gap:10px;flex-wrap:wrap;align-items:center'},
      h('span', {class: 'small muted'}, s.updated ? `Last saved ${when(s.updated)}${s.updated_by ? ' by ' + s.updated_by : ''}.` : 'Not saved yet.'), save));

  const check = async (p, btn) => {
    btn.disabled = true;
    try { await api(`/api/admin/payments/${encodeURIComponent(p.id)}/check`, {method: 'POST'}); notify('Checked with Razorpay', 'ok'); renderPayments(); }
    catch (e) { btn.disabled = false; notify(e.message, 'err'); }
  };
  const t = d.totals || {};
  const list = h('div', {class: 'card'}, h('h3', {}, 'Payments'),
    h('div', {class: 'muted small', style: 'margin:-6px 0 8px'}, 'Live payments, refunds taken off: '
      + ['INR', 'USD'].filter(c => c === 'INR' || (t[c] || {}).count).map(c => { const x = t[c] || {};
        return `${money(x.month, c, true)} this month, ${money(x.all, c, true)} in all (${x.count || 0})`; }).join('; ')
      + '. A checkout that was never paid is deleted after a year; paid ones are kept.'),
    d.payments.length ? h('div', {class: 'orgwrap'}, h('table', {class: 'utable'}, th(['When', 'Organisation', 'Who', 'Credits', 'Amount', 'Status', 'Razorpay', ''], 3),
      h('tbody', {}, d.payments.map(p => h('tr', {},
        h('td', {}, when(p.paid || p.created), p.live ? null : h('span', {class: 'tag', style: 'margin-left:6px'}, 'Test')),
        h('td', {}, h('b', {}, p.org_name || p.tenant_id)), h('td', {}, p.user_name || '—', h('div', {class: 'small muted'}, p.email || '')),
        h('td', {class: 'n'}, '+' + Number(p.credits).toLocaleString('en-IN')),
        h('td', {class: 'n'}, money(p.amount, p.currency, true), p.gst ? h('div', {class: 'small muted'}, `incl. ${money(p.gst, p.currency, true)} GST`) : null),
        h('td', {}, payState(p), p.method ? h('div', {class: 'small muted'}, PAY_METHODS[p.method] || p.method) : null,
          p.error ? h('div', {class: 'small muted'}, p.error) : null),
        h('td', {class: 'small'}, p.payment_id || '', h('div', {class: 'muted'}, p.order_id || '')),
        h('td', {class: 'n'}, p.status === 'created' || p.status === 'failed' ? (() => { const b = h('button', {class: 'btn sm', type: 'button',
          title: 'Ask Razorpay whether it was paid'}, 'Check'); b.onclick = () => check(p, b); return b; })() : null))))))
      : h('div', {class: 'muted small'}, 'None yet.'));

  page.append(
    h('div', {class: 'phead'}, h('div', {style: 'flex:1'}, h('div', {class: 'eyebrow'}, 'Platform'), h('h1', {}, 'Payments'),
      h('div', {class: 'meta'}, 'Organisations buy credit packs online through Razorpay; the credits are added once Razorpay confirms the payment. '
        + 'Requests for credits (invoices, bank transfer) stay under Requests.'))),
    h('div', {class: 'orggrid'}, selling, keys), list);
}
