# Maintenance production go-live checklist

Complete these items before enabling Phase 7 maintenance ticketing in production:

- [ ] Set the production RingCentral SMS sending number to `+12042598093` and verify its `SmsSender` feature before enabling outbound messages.
- [ ] Delete the staging RingCentral webhook subscription before creating the production subscription. Confirm that only the intended production subscription is active afterward.
- [ ] Install the committed `deploy/officehub-worker.service` and `deploy/officehub-beat.service` units, then enable and start both services at boot.
- [ ] Configure the on-call roster and confirm every admin fallback has `phone_e164` set before launch.
- [ ] Run `maintenance.renew_ringcentral_subscription`, confirm its expiry in `/health`, and verify the hourly renewal job is running under Celery beat.
- [ ] Decide which monitored 24/7 voice line tenants should call, set `PRIVI_EMERGENCY_PHONE` to that number, and verify the call routing before printing any QR cards.
- [ ] Correct tenant ID 7's invalid phone number in production data before running or relying on the maintenance phone backfill.
