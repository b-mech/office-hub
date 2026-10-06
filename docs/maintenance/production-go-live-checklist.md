# Maintenance production go-live checklist

Complete these items before enabling Phase 7 maintenance ticketing in production:

- [ ] Delete the staging RingCentral webhook subscription before creating the production subscription. Confirm that only the intended production subscription is active afterward.
- [ ] Install the committed `deploy/officehub-worker.service` and `deploy/officehub-beat.service` units, then enable and start both services at boot.
- [ ] Decide which monitored 24/7 voice line tenants should call, set `PRIVI_EMERGENCY_PHONE` to that number, and verify the call routing before printing any QR cards.
- [ ] Correct tenant ID 7's invalid phone number in production data before running or relying on the maintenance phone backfill.

