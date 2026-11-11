# Payments and digital products

Use for Stars, invoices, subscriptions, marketplaces, and delivery. Start from `assets/stars_ledger.py`. Confirm details with `tgdocs.py method createInvoiceLink`.

## Policy

- Digital goods and services must be sold in **Telegram Stars** (`XTR`). Third-party payment providers are for physical goods and services. See [developer terms §6](https://telegram.org/tos/bot-developers).
- Merchants must honor delivery, handle disputes, and respond to `/paysupport`. Stars can be refunded with no penalty.
- Offer terms (`/terms` or equivalent).
- In Mini Apps, crypto functions must be on TON, and wallets must connect through TON Connect.
- Physical goods use `sendInvoice` with a provider token and a real currency, in smallest units. Do not mix the two flows.

## Purchase flow

```
1. User picks product      → server creates an order (status: created, price from server)
2. sendInvoice             → payload = opaque order id; currency XTR; provider_token ""; one price item
3. pre_checkout_query      → re-validate; answer within 10 seconds; never deliver here
4. successful_payment      → record with charge id; idempotent
5. Deliver                 → claimed step; retryable
6. Confirm                 → receipt with reference and support path
```

Requirements:

- The `payload` (1–128 bytes) is an opaque order ID. Don't place prices, roles, or trusted data there.
- Re-check product availability, price, buyer, and order status at pre-checkout. Keep this fast and avoid external calls that could miss the 10-second limit. On failure use `ok=False` with a specific `error_message`.
- At `successful_payment`, compare currency, amount, and buyer to the order. A mismatch is an alert with refund or review. Money has been taken, so never drop it silently.
- Store `telegram_payment_charge_id`, which you need for refunds, under a unique constraint.
- Never trust the Mini App's `openInvoice` callback status for fulfilment. It's for UI only. The grant comes from the `successful_payment` update on the bot side.
- Keep the payment handlers out of any queue that can fall behind, because of the pre-checkout deadline.
- Include `pre_checkout_query` in `allowed_updates` when listing them explicitly.

Payment updates are delivered at least once. If `record_payment` commits and the delivery crashes, a retry sweep must find `paid` orders with no delivery. Run such a sweep at startup and on a timer.

## Delivery

| Product | Delivery |
|---|---|
| File | `file_id` from a private store; `protect_content` if appropriate |
| License key | Reserve atomically from a pool, one per order, in the claim transaction |
| Channel access | Single-use invite link with `member_limit=1`, or approve via join request |
| Feature or plan | Update an entitlement row with an expiry |

Delivery that fails permanently should trigger a refund or a human review. Do not leave a paid user with nothing.

## Subscriptions

- Create with `createInvoiceLink` and `subscription_period=2592000` (the only permitted value, 30 days). Price at most 10,000 Stars. `sendInvoice` has no such parameter.
- Each renewal arrives as a `successful_payment` with `is_recurring`, a new charge ID, and `subscription_expiration_date`. `is_first_recurring` marks the first. **Record one row per charge**, because `assets/stars_ledger.py` models one-shot orders, and extend the entitlement from the payment's expiry.
- Add `subscription` to `allowed_updates` when listing them. `BotSubscriptionUpdated.state` is `canceled`, `active`, or `failed`, available since Bot API 10.2. Check SDK support.
- Entitlement is decided by stored expiry, not by whether a message was sent. Use a small grace period and a scheduled expiry job.
- Cancel or re-enable with `editUserStarSubscription`.
- Channel subscriptions are a separate mechanism: `createChatSubscriptionInviteLink`.
- Tell users the renewal date and how to cancel, on the subscription screen.

## Refunds

`refundStarPayment(user_id, telegram_payment_charge_id)`, and a `refunded_payment` update may arrive. Revoke the entitlement in the same logical step. Make it idempotent, restrict it to authorized staff or a defined policy, audit-log it, and deal with "already refunded" errors. Keep policy windows configurable.

Reconcile against `getStarTransactions` on a schedule to find any gaps.

## Marketplaces

- Keep a ledger of immutable entries: sale, fee, payout, refund. Derive balances from it. Don't mutate a balance column alone.
- Use integers for Stars. Avoid floats.
- Authorize sellers on each listing and order action.
- Reserve stock inside the transaction, and release it if the order expires.
- Hold seller funds until delivery can no longer be disputed.
- Review the terms and local law before moving funds between users. Flag this for human or legal review rather than deciding it in code.

## Failure handling

| Failure | Response |
|---|---|
| Redelivered update | No-op via charge ID |
| Crash between record and delivery | Retry sweep |
| Double tap on Buy | One active order per user and SKU, or independent orders with a short TTL |
| Price changed after invoice | Reject at pre-checkout, offer the new price |
| Out of stock at pre-checkout | Reject with a clear message |
| Stale invoice | Order TTL |
| Refund succeeded, database write failed | Reconcile from Telegram's transaction list |

## Testing

Telegram's test environment takes Stars payments without real money. Offline, test the ledger: duplicate updates, wrong amounts, concurrent delivery, crash recovery, expiry, and refunds. Do not claim that a payment flow works in Telegram until it has been run on a test bot.
