# Razorpay Payment Integration (Test Mode)

A small Flask app that integrates Razorpay in **test mode**: order creation,
Checkout, payment signature verification, and webhook handling.

## Flow
1. Browser asks the server to create an order (`POST /create-order`, Razorpay Orders API).
2. Razorpay Checkout opens with the `order_id`.
3. After payment, Checkout returns `razorpay_order_id`, `razorpay_payment_id`, `razorpay_signature`.
4. Server verifies the signature (`POST /verify-payment`, HMAC SHA256 with the key secret).
5. Razorpay sends webhooks (`POST /webhook`); the server verifies `X-Razorpay-Signature`
   against the raw body and logs events (`GET /events`).

## Setup
```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # then add your TEST keys
python app.py
```
Open http://127.0.0.1:5000

## Webhook setup (local)
1. Run `ngrok http 5000` and copy the https URL.
2. Razorpay Dashboard (Test Mode) -> Settings -> Webhooks -> Add URL
   `https://<ngrok-id>.ngrok-free.app/webhook`, set a secret, enable
   `payment.captured`, `payment.failed`, `order.paid`.
3. Put the same secret in `.env` as `RAZORPAY_WEBHOOK_SECRET`.

## Scenarios tested / debugged
| Scenario | Result | How I debugged |
|---|---|---|
| Successful payment | Signature verified, `payment.captured` webhook logged | `app.log`, `/events` |
| Failed payment | `payment.failed` handled in Checkout and webhook | Checkout error + webhook payload |
| Tampered signature | `400 Signature verification failed` | Postman against `/verify-payment` |
| Invalid webhook signature | `400 Invalid signature` | Postman with wrong header |
| Wrong API keys | Order creation fails (auth error) | Server log + Razorpay error response |
| Amount below Rs 1 | `400` from the app | Input validation |

## Tech
Python, Flask, Razorpay Python SDK, Razorpay Checkout, Postman, ngrok
