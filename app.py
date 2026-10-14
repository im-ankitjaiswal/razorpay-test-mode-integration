"""Razorpay payment integration (TEST MODE) - v2.

Adds on top of v1: SQLite persistence, idempotent webhooks (duplicate
event protection), out-of-order event handling, refunds, stats API and
a dashboard UI.
"""
import hashlib
import json
import logging
import os
import sqlite3
from datetime import datetime, timezone

import razorpay
from dotenv import load_dotenv
from flask import Flask, g, jsonify, render_template, request

load_dotenv()

KEY_ID = os.getenv("RAZORPAY_KEY_ID")
KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")
WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET")
DB_PATH = os.getenv("DB_PATH", "payments.db")

if not KEY_ID or not KEY_SECRET:
    raise RuntimeError("Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET in .env")

app = Flask(__name__)
client = razorpay.Client(auth=(KEY_ID, KEY_SECRET))

logging.basicConfig(
    filename="app.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("razorpay-demo")

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    order_id   TEXT PRIMARY KEY,
    amount     INTEGER NOT NULL,
    currency   TEXT NOT NULL,
    receipt    TEXT,
    status     TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS payments (
    payment_id      TEXT PRIMARY KEY,
    order_id        TEXT,
    amount          INTEGER,
    currency        TEXT,
    status          TEXT,
    method          TEXT,
    verified        INTEGER NOT NULL DEFAULT 0,
    refunded_amount INTEGER NOT NULL DEFAULT 0,
    error           TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS webhook_events (
    event_id    TEXT PRIMARY KEY,
    event       TEXT,
    entity_id   TEXT,
    status      TEXT,
    received_at TEXT NOT NULL,
    payload     TEXT
);
"""


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(SCHEMA)


init_db()


def upsert_payment(db, p, verified=0):
    """Insert or update a payment. Never downgrade captured/refunded
    to an earlier state (webhooks can arrive out of order)."""
    ts = now()
    db.execute(
        """
        INSERT INTO payments
            (payment_id, order_id, amount, currency, status, method,
             verified, error, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(payment_id) DO UPDATE SET
            order_id = COALESCE(excluded.order_id, payments.order_id),
            amount   = COALESCE(excluded.amount, payments.amount),
            currency = COALESCE(excluded.currency, payments.currency),
            method   = COALESCE(excluded.method, payments.method),
            error    = COALESCE(excluded.error, payments.error),
            verified = MAX(payments.verified, excluded.verified),
            status   = CASE
                WHEN payments.status IN ('captured', 'refunded')
                     AND excluded.status IN ('created', 'authorized')
                THEN payments.status
                ELSE COALESCE(excluded.status, payments.status)
            END,
            updated_at = excluded.updated_at
        """,
        (
            p.get("id"), p.get("order_id"), p.get("amount"), p.get("currency"),
            p.get("status"), p.get("method"), verified,
            p.get("error_description"), ts, ts,
        ),
    )


# ---------------------------------------------------------------- pages
@app.route("/")
def index():
    return render_template("index.html", key_id=KEY_ID)


# ---------------------------------------------------------------- orders
@app.route("/create-order", methods=["POST"])
def create_order():
    data = request.get_json(silent=True) or {}
    try:
        rupees = float(data.get("amount", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid amount"}), 400
    if rupees < 1:
        return jsonify({"error": "Minimum amount is Rs 1"}), 400

    payload = {
        "amount": int(round(rupees * 100)),
        "currency": "INR",
        "receipt": f"rcpt_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}",
    }
    try:
        order = client.order.create(data=payload)
    except Exception as exc:
        log.error("Order creation failed: %s", exc)
        return jsonify({"error": "Order creation failed", "details": str(exc)}), 502

    db = get_db()
    db.execute(
        "INSERT INTO orders (order_id, amount, currency, receipt, status, created_at)"
        " VALUES (?,?,?,?,?,?)",
        (order["id"], order["amount"], order["currency"], payload["receipt"],
         "created", now()),
    )
    db.commit()
    log.info("Order created: %s amount=%s", order["id"], order["amount"])
    return jsonify(
        {"order_id": order["id"], "amount": order["amount"], "currency": order["currency"]}
    )


# ---------------------------------------------------------------- verify
@app.route("/verify-payment", methods=["POST"])
def verify_payment():
    data = request.get_json(silent=True) or {}
    params = {
        "razorpay_order_id": data.get("razorpay_order_id"),
        "razorpay_payment_id": data.get("razorpay_payment_id"),
        "razorpay_signature": data.get("razorpay_signature"),
    }
    if not all(params.values()):
        return jsonify({"status": "failed", "error": "Missing fields"}), 400
    try:
        client.utility.verify_payment_signature(params)
    except razorpay.errors.SignatureVerificationError:
        log.warning("Signature mismatch for order %s", params["razorpay_order_id"])
        return jsonify({"status": "failed", "error": "Signature verification failed"}), 400

    pid, oid = params["razorpay_payment_id"], params["razorpay_order_id"]
    db = get_db()
    try:
        details = client.payment.fetch(pid)
    except Exception as exc:  # keep going with minimal data
        log.warning("Could not fetch payment %s: %s", pid, exc)
        details = {"id": pid, "order_id": oid}
    upsert_payment(db, details, verified=1)
    db.commit()
    log.info("Payment verified: %s", pid)
    return jsonify({"status": "success", "payment_id": pid})


@app.route("/payment-failed", methods=["POST"])
def payment_failed():
    """Record a failure reported by Checkout (browser side)."""
    data = request.get_json(silent=True) or {}
    pid = data.get("payment_id")
    if not pid:
        return jsonify({"error": "payment_id required"}), 400
    db = get_db()
    upsert_payment(
        db,
        {"id": pid, "order_id": data.get("order_id"), "status": "failed",
         "error_description": data.get("description")},
    )
    db.commit()
    log.warning("Payment failed (checkout): %s %s", pid, data.get("description"))
    return jsonify({"status": "recorded"})


# ---------------------------------------------------------------- webhook
@app.route("/webhook", methods=["POST"])
def webhook():
    if not WEBHOOK_SECRET:
        return jsonify({"error": "Webhook secret not configured"}), 500

    body = request.get_data(as_text=True)
    signature = request.headers.get("X-Razorpay-Signature", "")
    try:
        client.utility.verify_webhook_signature(body, signature, WEBHOOK_SECRET)
    except razorpay.errors.SignatureVerificationError:
        log.warning("Invalid webhook signature")
        return jsonify({"error": "Invalid signature"}), 400

    event = json.loads(body or "{}")
    event_name = event.get("event")
    payload = event.get("payload", {})
    pay = (payload.get("payment") or {}).get("entity")
    order = (payload.get("order") or {}).get("entity")
    entity = pay or order or {}

    # Razorpay retries deliveries, so de-duplicate on the event id.
    event_id = request.headers.get("X-Razorpay-Event-Id") or hashlib.sha256(
        body.encode()
    ).hexdigest()

    db = get_db()
    try:
        if db.execute("SELECT 1 FROM webhook_events WHERE event_id=?", (event_id,)).fetchone():
            log.info("Duplicate webhook ignored: %s", event_id)
            return jsonify({"status": "duplicate"}), 200

        db.execute(
            "INSERT INTO webhook_events (event_id, event, entity_id, status, received_at, payload)"
            " VALUES (?,?,?,?,?,?)",
            (event_id, event_name, entity.get("id"), entity.get("status"), now(), body),
        )
        if pay:
            upsert_payment(db, pay)
        if order:
            db.execute("UPDATE orders SET status=? WHERE order_id=?",
                       (order.get("status"), order.get("id")))
        db.commit()
    except Exception as exc:
        db.rollback()
        log.error("Webhook processing failed: %s", exc)
        return jsonify({"error": "processing failed"}), 500  # Razorpay will retry

    log.info("Webhook processed: %s id=%s", event_name, entity.get("id"))
    return jsonify({"status": "ok"}), 200


# ---------------------------------------------------------------- refunds
@app.route("/refund/<payment_id>", methods=["POST"])
def refund(payment_id):
    data = request.get_json(silent=True) or {}
    db = get_db()
    row = db.execute("SELECT * FROM payments WHERE payment_id=?", (payment_id,)).fetchone()
    if not row:
        return jsonify({"error": "Payment not found"}), 404
    if row["status"] not in ("captured", "refunded"):
        return jsonify({"error": f"Only captured payments can be refunded (status: {row['status']})"}), 400

    remaining = (row["amount"] or 0) - row["refunded_amount"]
    if remaining <= 0:
        return jsonify({"error": "Payment already fully refunded"}), 400

    if data.get("amount") in (None, ""):
        paise = remaining
    else:
        try:
            paise = int(round(float(data["amount"]) * 100))
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid amount"}), 400
    if paise < 100 or paise > remaining:
        return jsonify({"error": "Refund must be at least Rs 1 and not exceed the remaining amount"}), 400

    try:
        result = client.payment.refund(payment_id, {"amount": paise})
    except Exception as exc:
        log.error("Refund failed for %s: %s", payment_id, exc)
        return jsonify({"error": "Refund failed", "details": str(exc)}), 502

    refunded = row["refunded_amount"] + paise
    status = "refunded" if refunded >= (row["amount"] or 0) else row["status"]
    db.execute(
        "UPDATE payments SET refunded_amount=?, status=?, updated_at=? WHERE payment_id=?",
        (refunded, status, now(), payment_id),
    )
    db.commit()
    log.info("Refund %s for %s amount=%s", result.get("id"), payment_id, paise)
    return jsonify({"status": "refunded", "refund_id": result.get("id"), "amount": paise})


# ---------------------------------------------------------------- APIs
@app.route("/api/payments")
def api_payments():
    rows = get_db().execute("SELECT * FROM payments ORDER BY updated_at DESC LIMIT 50").fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/orders")
def api_orders():
    rows = get_db().execute("SELECT * FROM orders ORDER BY created_at DESC LIMIT 50").fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/events")
@app.route("/events")
def api_events():
    rows = get_db().execute(
        "SELECT * FROM webhook_events ORDER BY received_at DESC LIMIT 50"
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/stats")
def api_stats():
    db = get_db()
    s = db.execute(
        """SELECT
             COALESCE(SUM(CASE WHEN status IN ('captured','refunded') THEN amount END), 0) AS collected,
             COALESCE(SUM(refunded_amount), 0) AS refunded,
             COUNT(*) AS total,
             SUM(CASE WHEN status IN ('captured','refunded') THEN 1 ELSE 0 END) AS success,
             SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed
           FROM payments"""
    ).fetchone()
    total = s["total"] or 0
    success = s["success"] or 0
    return jsonify(
        {
            "collected": s["collected"],
            "refunded": s["refunded"],
            "total": total,
            "success": success,
            "failed": s["failed"] or 0,
            "success_rate": round(100 * success / total, 1) if total else 0,
        }
    )


if __name__ == "__main__":
    app.run(port=5000, debug=True)
