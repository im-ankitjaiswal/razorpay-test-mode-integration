"""Run with:  python -m unittest discover -s tests -v"""
import hashlib
import hmac
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["RAZORPAY_KEY_ID"] = "rzp_test_dummy"
os.environ["RAZORPAY_KEY_SECRET"] = "dummy_secret"
os.environ["RAZORPAY_WEBHOOK_SECRET"] = "hook_secret"
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["DB_PATH"] = _tmp.name

import app as app_module  # noqa: E402


def sign(secret, message):
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def webhook_body(event, pid="pay_1", status="captured", oid="order_1", amount=10000):
    return json.dumps(
        {"event": event,
         "payload": {"payment": {"entity": {
             "id": pid, "order_id": oid, "amount": amount, "currency": "INR",
             "status": status, "method": "upi"}}}}
    )


class AppTests(unittest.TestCase):
    def setUp(self):
        with app_module.app.app_context():
            db = app_module.get_db()
            for t in ("orders", "payments", "webhook_events"):
                db.execute(f"DELETE FROM {t}")
            db.commit()
        self.c = app_module.app.test_client()

    def post_hook(self, body, secret="hook_secret", event_id="evt_1"):
        return self.c.post(
            "/webhook", data=body,
            headers={"X-Razorpay-Signature": sign(secret, body),
                     "X-Razorpay-Event-Id": event_id,
                     "Content-Type": "application/json"},
        )

    def test_create_order_validation(self):
        self.assertEqual(self.c.post("/create-order", json={"amount": 0}).status_code, 400)
        self.assertEqual(self.c.post("/create-order", json={"amount": "abc"}).status_code, 400)

    def test_create_order_saved(self):
        fake = {"id": "order_X", "amount": 50000, "currency": "INR"}
        with patch.object(app_module.client.order, "create", return_value=fake):
            r = self.c.post("/create-order", json={"amount": 500})
        self.assertEqual(r.get_json()["order_id"], "order_X")
        self.assertEqual(len(self.c.get("/api/orders").get_json()), 1)

    def test_verify_payment_good_and_bad_signature(self):
        good = sign("dummy_secret", "order_1|pay_1")
        fake = {"id": "pay_1", "order_id": "order_1", "amount": 10000,
                "currency": "INR", "status": "captured", "method": "card"}
        with patch.object(app_module.client.payment, "fetch", return_value=fake):
            ok = self.c.post("/verify-payment", json={
                "razorpay_order_id": "order_1", "razorpay_payment_id": "pay_1",
                "razorpay_signature": good})
        self.assertEqual(ok.status_code, 200)
        bad = self.c.post("/verify-payment", json={
            "razorpay_order_id": "order_1", "razorpay_payment_id": "pay_1",
            "razorpay_signature": "tampered"})
        self.assertEqual(bad.status_code, 400)

    def test_webhook_invalid_signature(self):
        r = self.post_hook(webhook_body("payment.captured"), secret="wrong")
        self.assertEqual(r.status_code, 400)

    def test_webhook_stored_and_duplicate_ignored(self):
        body = webhook_body("payment.captured")
        self.assertEqual(self.post_hook(body).get_json()["status"], "ok")
        self.assertEqual(self.post_hook(body).get_json()["status"], "duplicate")
        self.assertEqual(len(self.c.get("/api/events").get_json()), 1)
        self.assertEqual(self.c.get("/api/payments").get_json()[0]["status"], "captured")

    def test_out_of_order_event_does_not_downgrade(self):
        self.post_hook(webhook_body("payment.captured", status="captured"), event_id="e1")
        self.post_hook(webhook_body("payment.authorized", status="authorized"), event_id="e2")
        self.assertEqual(self.c.get("/api/payments").get_json()[0]["status"], "captured")

    def test_refund_rules(self):
        self.post_hook(webhook_body("payment.captured"), event_id="e1")
        too_much = self.c.post("/refund/pay_1", json={"amount": 500})
        self.assertEqual(too_much.status_code, 400)
        with patch.object(app_module.client.payment, "refund", return_value={"id": "rfnd_1"}):
            part = self.c.post("/refund/pay_1", json={"amount": 40})
            self.assertEqual(part.status_code, 200)
            rest = self.c.post("/refund/pay_1", json={})
            self.assertEqual(rest.status_code, 200)
        self.assertEqual(self.c.get("/api/payments").get_json()[0]["status"], "refunded")
        self.assertEqual(self.c.post("/refund/pay_1", json={}).status_code, 400)

    def test_refund_requires_captured(self):
        self.post_hook(webhook_body("payment.authorized", status="authorized"), event_id="e1")
        self.assertEqual(self.c.post("/refund/pay_1", json={}).status_code, 400)

    def test_stats(self):
        self.post_hook(webhook_body("payment.captured", pid="pay_a"), event_id="e1")
        self.post_hook(webhook_body("payment.failed", pid="pay_b", status="failed"), event_id="e2")
        s = self.c.get("/api/stats").get_json()
        self.assertEqual((s["total"], s["success"], s["failed"]), (2, 1, 1))
        self.assertEqual(s["success_rate"], 50.0)


if __name__ == "__main__":
    unittest.main()
