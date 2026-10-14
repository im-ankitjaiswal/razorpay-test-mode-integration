"""Razorpay payment integration (TEST MODE) - Flask demo.

Covers: Orders API, Checkout, payment signature verification,
webhook signature verification and basic event logging.
"""
import logging
import os
from datetime import datetime

import razorpay
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

load_dotenv()

KEY_ID = os.getenv("RAZORPAY_KEY_ID")
KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")
WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET")

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

# Simple in-memory store of webhook events (resets on restart)
EVENTS = []


@app.route("/")
def index():
    return render_template("index.html", key_id=KEY_ID)


@app.route("/create-order", methods=["POST"])
def create_order():
    """Step 1: create an order on the server (amount is in paise)."""
    data = request.get_json(silent=True) or {}
    try:
        rupees = float(data.get("amount", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid amount"}), 400
    if rupees < 1:
        return jsonify({"error": "Minimum amount is Rs 1"}), 400

    payload = {
        "amount": int(round(rupees * 100)),  # paise
        "currency": "INR",
        "receipt": f"rcpt_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
    }
    try:
        order = client.order.create(data=payload)
    except Exception as exc:  # e.g. bad keys -> 401 from Razorpay
        log.error("Order creation failed: %s", exc)
        return jsonify({"error": "Order creation failed", "details": str(exc)}), 502

    log.info("Order created: %s amount=%s", order["id"], order["amount"])
    return jsonify(
        {"order_id": order["id"], "amount": order["amount"], "currency": order["currency"]}
    )


@app.route("/verify-payment", methods=["POST"])
def verify_payment():
    """Step 3: verify the signature returned by Checkout.
    Signature = HMAC_SHA256(order_id + '|' + payment_id, key_secret)
    """
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

    log.info("Payment verified: %s", params["razorpay_payment_id"])
    return jsonify({"status": "success", "payment_id": params["razorpay_payment_id"]})


@app.route("/webhook", methods=["POST"])
def webhook():
    """Step 4: receive Razorpay webhooks. Verify against the RAW body."""
    if not WEBHOOK_SECRET:
        return jsonify({"error": "Webhook secret not configured"}), 500

    body = request.get_data(as_text=True)
    signature = request.headers.get("X-Razorpay-Signature", "")
    try:
        client.utility.verify_webhook_signature(body, signature, WEBHOOK_SECRET)
    except razorpay.errors.SignatureVerificationError:
        log.warning("Invalid webhook signature")
        return jsonify({"error": "Invalid signature"}), 400

    event = request.get_json(silent=True) or {}
    event_name = event.get("event")
    entity = (
        event.get("payload", {}).get("payment", {}).get("entity", {})
        or event.get("payload", {}).get("order", {}).get("entity", {})
    )
    EVENTS.append(
        {
            "time": datetime.utcnow().isoformat(),
            "event": event_name,
            "id": entity.get("id"),
            "status": entity.get("status"),
        }
    )
    log.info("Webhook received: %s id=%s", event_name, entity.get("id"))
    # Always return 200 quickly so Razorpay does not retry
    return jsonify({"status": "ok"}), 200


@app.route("/events")
def events():
    """View received webhook events."""
    return jsonify(EVENTS)


if __name__ == "__main__":
    app.run(port=5000, debug=True)
