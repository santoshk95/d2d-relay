/* Test stack only: stands in for https://checkout.razorpay.com/v1/checkout.js in a headless browser. window.__rzpMode:
   'pay' (default: the stand-in Razorpay records a card payment and the handler gets its ids and signature),
   'dismiss' (the person closes the window), 'fail' (the payment fails, then the window is closed). */
window.__rzp = window.__rzp || {opened: []};
window.Razorpay = function (opts) {
  const handlers = {};
  this.on = (ev, fn) => { handlers[ev] = fn; };
  this.open = () => {
    const mode = window.__rzpMode || 'pay';
    window.__rzp.opened.push({key: opts.key, amount: opts.amount, currency: opts.currency, order_id: opts.order_id, name: opts.name,
      description: opts.description, prefill: opts.prefill, theme: opts.theme, notes: opts.notes, mode});
    setTimeout(async () => {
      if (mode === 'dismiss') { opts.modal.ondismiss(); return; }
      if (mode === 'fail') {
        handlers['payment.failed']({error: {code: 'BAD_REQUEST_ERROR', description: 'Card declined (test)', metadata: {order_id: opts.order_id}}});
        setTimeout(() => opts.modal.ondismiss(), 400);
        return;
      }
      const r = await fetch('http://127.0.0.1:9911/_test/pay', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({order_id: opts.order_id, status: 'captured', method: 'card'})}).then(x => x.json());
      opts.handler({razorpay_order_id: r.razorpay_order_id, razorpay_payment_id: r.razorpay_payment_id, razorpay_signature: r.razorpay_signature});
    }, 300);
  };
};
