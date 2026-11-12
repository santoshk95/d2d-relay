"""A stand-in for Razorpay's API, for the D2D Relay test stack only (never live). Standard library only.

Runs inside the test web container (docker exec -d), on 0.0.0.0:9911:
  POST /v1/orders, GET /v1/orders/<id>, GET /v1/orders/<id>/payments, GET /v1/payments/<id>, POST /v1/payments/<id>/capture
  (HTTP Basic auth with FAKE_RZP_KEY_ID / FAKE_RZP_SECRET, Razorpay's error shape)
and, for the tests ("the customer"):
  POST /_test/pay    {order_id, status: captured|authorized|failed, amount?, currency?, method?, pay_order_id?}
                     -> {razorpay_order_id, razorpay_payment_id, razorpay_signature, payment}
  POST /_test/down   {seconds}: answer 503 to API calls for that long
  GET  /_test/state  counts
CORS is open so a browser test's stub checkout can call /_test/pay.
"""
import base64
import hashlib
import hmac
import json
import os
import random
import re
import string
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

KEY_ID = os.environ["FAKE_RZP_KEY_ID"]
SECRET = os.environ["FAKE_RZP_SECRET"]
ORDERS: dict = {}
PAYMENTS: dict = {}
STATE = {"down_until": 0.0, "orders": 0, "captures": 0, "calls": 0}
LOCK = threading.Lock()


def rid(prefix: str) -> str:
    return prefix + "".join(random.choice(string.ascii_letters + string.digits) for _ in range(14))


def err(description: str, code: str = "BAD_REQUEST_ERROR") -> dict:
    return {"error": {"code": code, "description": description, "source": "NA", "step": "NA", "reason": "NA", "metadata": {}}}


class H(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):            # quiet
        pass

    def _send(self, code: int, obj) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        try:
            return json.loads(raw or b"{}")
        except ValueError:
            return {}

    def _gate(self) -> bool:
        """False when the call was answered already (down, or wrong keys)."""
        STATE["calls"] += 1
        if time.time() < STATE["down_until"]:
            self._send(503, err("Razorpay is down (test)", "SERVER_ERROR"))
            return False
        want = "Basic " + base64.b64encode(f"{KEY_ID}:{SECRET}".encode()).decode()
        if self.headers.get("Authorization") != want:
            self._send(401, err("Authentication failed"))
            return False
        return True

    def do_OPTIONS(self):                         # a browser's CORS preflight: no body
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/_test/state":
            return self._send(200, {**STATE, "order_count": len(ORDERS), "payment_count": len(PAYMENTS)})
        if not self._gate():
            return
        with LOCK:
            m = re.match(r"^/v1/orders/(order_\w+)/payments$", path)
            if m:
                if m.group(1) not in ORDERS:
                    return self._send(400, err("The id provided does not exist"))
                items = [p for p in PAYMENTS.values() if p["order_id"] == m.group(1)]
                return self._send(200, {"entity": "collection", "count": len(items), "items": items})
            m = re.match(r"^/v1/orders/(order_\w+)$", path)
            if m:
                o = ORDERS.get(m.group(1))
                return self._send(200, o) if o else self._send(400, err("The id provided does not exist"))
            m = re.match(r"^/v1/payments/(pay_\w+)$", path)
            if m:
                p = PAYMENTS.get(m.group(1))
                return self._send(200, p) if p else self._send(400, err("The id provided does not exist"))
        return self._send(404, err("The requested URL was not found on the server."))

    def do_POST(self):
        path = self.path.split("?")[0]
        b = self._body()
        if path.startswith("/_test/"):
            return self._test(path, b)
        if not self._gate():
            return
        with LOCK:
            if path == "/v1/orders":
                amount, notes, cur = b.get("amount"), b.get("notes") or {}, b.get("currency")
                if cur not in ("INR", "USD"):
                    return self._send(400, err("Currency is not supported"))
                if not isinstance(amount, int) or amount < (100 if cur == "INR" else 50):
                    return self._send(400, err("Order amount less than minimum amount allowed"))
                if len(str(b.get("receipt") or "")) > 40:
                    return self._send(400, err("receipt: the length must be no more than 40."))
                if not isinstance(notes, dict) or len(notes) > 15 or any(len(str(v)) > 256 for v in notes.values()):
                    return self._send(400, err("notes: too many or too long"))
                o = {"id": rid("order_"), "entity": "order", "amount": amount, "amount_paid": 0, "amount_due": amount, "currency": cur,
                     "receipt": b.get("receipt"), "offer_id": None, "status": "created", "attempts": 0, "notes": notes,
                     "created_at": int(time.time())}
                ORDERS[o["id"]] = o
                STATE["orders"] += 1
                return self._send(200, o)
            m = re.match(r"^/v1/payments/(pay_\w+)/capture$", path)
            if m:
                p = PAYMENTS.get(m.group(1))
                if not p:
                    return self._send(400, err("The id provided does not exist"))
                if p["status"] == "captured":
                    return self._send(400, err("This payment has already been captured"))
                if p["status"] != "authorized":
                    return self._send(400, err("Only payments which have been authorized and not yet captured can be captured"))
                if b.get("amount") != p["amount"] or b.get("currency") != p["currency"]:
                    return self._send(400, err("Capture amount must be equal to the amount authorized"))
                p.update(status="captured", captured=True)
                o = ORDERS.get(p["order_id"])
                if o:
                    o.update(status="paid", amount_paid=p["amount"], amount_due=0)
                STATE["captures"] += 1
                return self._send(200, p)
        return self._send(404, err("The requested URL was not found on the server."))

    def _test(self, path: str, b: dict):
        with LOCK:
            if path == "/_test/pay":
                o = ORDERS.get(b.get("order_id"))
                if not o:
                    return self._send(404, err("no such order (test)"))
                st = b.get("status", "captured")
                pid = rid("pay_")
                p = {"id": pid, "entity": "payment", "amount": int(b.get("amount", o["amount"])), "currency": b.get("currency", o["currency"]),
                     "status": st, "order_id": b.get("pay_order_id", o["id"]), "invoice_id": None, "international": False,
                     "method": b.get("method", "upi"), "amount_refunded": 0, "refund_status": None, "captured": st == "captured",
                     "description": "test", "email": "buyer@example.com", "contact": "+919000000000", "fee": None, "tax": None,
                     "error_code": "BAD_REQUEST_ERROR" if st == "failed" else None,
                     "error_description": "Payment failed (test)" if st == "failed" else None,
                     "error_reason": "payment_failed" if st == "failed" else None, "created_at": int(time.time())}
                if p["currency"] != "INR":                 # Razorpay converts foreign currency: its rupee value (here at 93.5 a dollar)
                    p.update(base_amount=p["amount"] * 935 // 10, base_currency="INR")
                PAYMENTS[pid] = p
                o["attempts"] += 1
                if st == "captured" and p["order_id"] == o["id"]:
                    o.update(status="paid", amount_paid=p["amount"], amount_due=0)
                elif o["status"] == "created":
                    o["status"] = "attempted"
                sig = hmac.new(SECRET.encode(), f"{o['id']}|{pid}".encode(), hashlib.sha256).hexdigest()
                return self._send(200, {"razorpay_order_id": o["id"], "razorpay_payment_id": pid, "razorpay_signature": sig, "payment": p})
            if path == "/_test/down":
                STATE["down_until"] = time.time() + float(b.get("seconds") or 0)
                return self._send(200, {"down_until": STATE["down_until"]})
        return self._send(404, err("no such test call"))


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("FAKE_RZP_PORT") or 9911)), H).serve_forever()
