# Razorpay Payment Integration (Test Mode)

A Flask application that integrates Razorpay in **test mode**. It covers server-side order creation, Razorpay Checkout, payment signature verification, refunds, and a dashboard for reviewing payments.

> Test mode only. No real money is processed.

## Why I built this
To understand how a payment gateway integration works end to end, and to practise the kind of debugging a technical support engineer does: reading API responses, checking logs, verifying signatures, and tracing a payment through the Razorpay dashboard.

## Features
- **Orders API:** orders are created on the server, with amounts converted to paise
- **Razorpay Checkout:** opened in the browser using the generated `order_id`
- **Payment signature verification:** HMAC SHA256 of `order_id|payment_id` using the key secret
- **Refunds:** full or partial, validated against the remaining refundable amount
- **Failure tracking:** failed Checkout attempts are stored with Razorpay's error description
- **Dashboard:** live stats (collected, payment count, success rate, refunded) and a payments table
- **SQLite storage** and **application logging** (`app.log`)

## Payment flow
```
1. Customer clicks Pay
        |
        v
2. Server creates an order  --->  Razorpay Orders API
        |
        v
3. Browser opens Razorpay Checkout with the order_id
        |
        v
4. Customer pays (card / UPI) and Razorpay returns
   payment_id + signature
        |
        v
5. Server verifies the signature
        |
        v
6. Payment is saved and shown on the dashboard
```

## Screenshots

### 1. Checkout page
![Checkout page](https://github.com/im-ankitjaiswal/razorpay-test-mode-integration/blob/main/01-checkout-page.png.jpeg)
*Amount entry with quick-select buttons.*

### 2. Razorpay Checkout popup
![Checkout popup](https://github.com/im-ankitjaiswal/razorpay-test-mode-integration/blob/main/02-checkout-popup.png.jpeg)
*Razorpay Checkout in test mode.*

### 3. OTP verification
![OTP verification](https://github.com/im-ankitjaiswal/razorpay-test-mode-integration/blob/main/03-otp-verification.png.jpeg)
*Domestic test card with the OTP step.*

### 4. Successful payment
![Payment successful](https://github.com/im-ankitjaiswal/razorpay-test-mode-integration/blob/main/04-payment-successful.png.jpeg)
*Payment completed successfully.*

### 5. Payment in the Razorpay dashboard
![Razorpay dashboard payments](https://github.com/im-ankitjaiswal/razorpay-test-mode-integration/blob/main/05-razorpay-dashboard-payments.png.jpeg)
*The same payments in the Razorpay dashboard (Test Mode), including the payment declined because international cards were not allowed.*

### 6. Application dashboard
![Application dashboard](https://github.com/im-ankitjaiswal/razorpay-test-mode-integration/blob/main/06-dashboard-overview.png.jpeg)
*Stats and payments table, with a Refund action for captured payments.*

### 7. Application log
![Application log](https://github.com/im-ankitjaiswal/razorpay-test-mode-integration/blob/main/07-app-log.png.jpeg)
*Order creation and payment verification logged by the server.*

## Tech stack
Python, Flask, SQLite, Razorpay Python SDK, Razorpay Checkout (JavaScript), HTML/CSS, Postman

## Project structure
```
.
|-- app.py                 # Routes, signature verification, refunds, database
|-- templates/
|   `-- index.html         # Checkout and dashboard UI
|-- tests/
|   `-- test_app.py        # Unit tests
|-- screenshots/           # Images used in this README
|-- requirements.txt
|-- .env.example           # Template for environment variables
|-- .gitignore
`-- README.md
```

## API endpoints
| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/` | Checkout and dashboard UI |
| POST | `/create-order` | Create a Razorpay order (rupees in, paise sent to Razorpay) |
| POST | `/verify-payment` | Verify the signature returned by Checkout and store the payment |
| POST | `/payment-failed` | Record a failure reported by Checkout |
| POST | `/refund/<payment_id>` | Full or partial refund |
| GET | `/api/payments` | Recent payments |
| GET | `/api/orders` | Recent orders |
| GET | `/api/stats` | Totals and success rate |

---

## Run it locally, step by step (Windows and VS Code)

### 1. Prerequisites
- Python 3.10 or newer (check with `python --version`)
- VS Code with the Python extension
- A Razorpay account (free)

### 2. Get the code
```bash
git clone https://github.com/im-ankitjaiswal/YOUR-REPO-NAME.git
cd YOUR-REPO-NAME
```
Or download the ZIP and open the folder in VS Code.

### 3. Create the virtual environment and install packages
Open a terminal in the project folder:
```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```
On Mac or Linux, activate with `source venv/bin/activate`.

### 4. Select the venv in VS Code
1. Press `Ctrl+Shift+P` and choose **Python: Select Interpreter**.
2. Pick `.\venv\Scripts\python.exe`.

This lets you use the Run button without activating the venv manually.

### 5. Get Razorpay test keys
1. Log in at dashboard.razorpay.com and switch to **Test Mode** (toggle at the top).
2. Go to **Account & Settings, API Keys, Generate Test Key**.
3. Copy the **Key ID** (`rzp_test_...`) and the **Key Secret**. The secret is shown only once.

Account activation and KYC are only needed for live payments, not for test mode.

### 6. Create your `.env` file
Copy `.env.example` to a new file named exactly `.env` (not `.env.txt`) and fill in your keys:
```
RAZORPAY_KEY_ID=rzp_test_xxxxxxxxxxxx
RAZORPAY_KEY_SECRET=your_test_key_secret
```
No quotes and no spaces around `=`. Never commit `.env`. It is already in `.gitignore`.

### 7. Run the app
Open `app.py` and click the Run button (or press `F5`), or run this in a terminal with `(venv)` active:
```powershell
python app.py
```
Open **http://127.0.0.1:5000**. If you change `.env`, stop the app and start it again.

### 8. Make a test payment
1. On the Checkout tab, enter an amount and click **Pay now**.
2. Pay with a test method:
   - UPI: `success@razorpay` (success) or `failure@razorpay` (failure)
   - Card: a domestic test card from Razorpay's test card documentation, with any future expiry, any CVV and any OTP. The standard `4111 1111 1111 1111` card may be declined as international on a domestic-only account.
3. The payment appears on the **Dashboard** tab and in the Razorpay dashboard under Transactions, Payments (Test Mode).

### 9. Try a refund
1. On the Dashboard tab, click **Refund** next to a captured payment.
2. Enter an amount in INR for a partial refund, or leave it blank for a full refund.
3. Check the result in three places: the dashboard (refunded amount), `app.log`, and the Razorpay dashboard under Transactions, Refunds.

Refunds only work on **captured** payments. In test mode no real money moves, so "processed" in Razorpay is the end of the testable flow.

### 10. Run the tests (optional)
```powershell
python -m unittest discover -s tests -v
```

---

## Test scenarios
| Scenario | Expected result | Status |
|---|---|---|
| Successful payment (domestic card with OTP) | Signature verified, payment stored | Tested |
| International card on a domestic-only account | Payment declined by Razorpay | Tested |
| Partial refund | Refunded amount updated, payment stays captured | Tested |
| Failed payment (`failure@razorpay`) | "Payment failed" shown, recorded as failed | Update after testing |
| Tampered payment signature (Postman) | 400, signature verification failed | Update after testing |
| Wrong API keys | Order creation fails with an auth error | Update after testing |
| Amount below Rs 1 | 400 from input validation | Update after testing |

## Issues I debugged
- **International card declined:** the standard test card was treated as international and the test account did not allow it. Fixed by using a domestic test card with OTP. Confirmed in the Checkout error, the Razorpay dashboard and `app.log`.
- **Missing keys at startup:** the keys were in `.env.example` instead of `.env`, so the app could not load them. Fixed by moving them to `.env` and keeping only placeholders in `.env.example`.
- **`ModuleNotFoundError: razorpay`:** the app was run outside the virtual environment. Fixed by activating the venv and selecting the venv interpreter in VS Code.
- *(Add anything else you hit, and how you found the cause.)*

## What I learned
- Why orders are created on the server, and why amounts are in paise
- Why the payment signature must be verified server-side and never trusted from the browser
- How to trace a payment through the Razorpay dashboard, API responses and logs
- How refunds work, including partial refunds, and why only captured payments can be refunded

## Security notes
- Keys are stored in `.env`, which is excluded by `.gitignore`
- Only test keys are used. Never commit live keys
- `payments.db` and `app.log` are also excluded from the repository

## Next steps
- Webhook handling with signature verification, so payment and refund status updates are received automatically
- Track refund status (pending, processed, failed) in the database
- Reconcile the local database against Razorpay's payment list
- Containerise with Docker and deploy
