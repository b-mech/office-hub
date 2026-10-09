# Maintenance production go-live checklist

Complete these items before enabling Phase 7 maintenance ticketing in production:

- [ ] Set the production RingCentral SMS sending number to `+12042598093` and verify its `SmsSender` feature before enabling outbound messages.
- [ ] Generate and configure a 1–32 character RingCentral webhook verification token (use 32 alphanumeric characters). The backend must refuse to start if the token is empty or longer than 32 characters.
- [ ] Delete the staging RingCentral webhook subscription before creating the production subscription. Create the production subscription exactly once with `deliveryMode.verificationToken` in the initial request, then confirm that only the intended production subscription is active.
- [ ] Before launch, send a real inbound SMS and verify that RingCentral's delivery carries the matching `Verification-Token` header and receives HTTP 200. Confirm the message was persisted by the webhook and was not recovered by message-store reconciliation.
- [ ] Install the committed `deploy/officehub-worker.service` and `deploy/officehub-beat.service` units, then enable and start both services at boot.
- [ ] Configure the on-call roster and confirm every admin fallback has `phone_e164` set before launch.
- [ ] Run `maintenance.renew_ringcentral_subscription`, confirm its expiry in `/health`, and verify the hourly renewal job is running under Celery beat. Renewal must keep the same subscription ID and use a full `PUT` containing `deliveryMode.verificationToken`; do not use RingCentral's `/renew` endpoint because it cannot deterministically preserve the token.
- [ ] Decide which monitored 24/7 voice line tenants should call, set `PRIVI_EMERGENCY_PHONE` to that number, and verify the call routing before printing any QR cards.
- [ ] Correct tenant ID 7's invalid phone number in production data before running or relying on the maintenance phone backfill.
