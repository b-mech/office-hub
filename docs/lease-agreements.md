# Rental lease agreements v1

The approved template is `backend/app/templates/leases/residential_tenancy_agreement_v1.docx` and its source is Box `PRIVI/Rentals/zzz-devdocs`. Do not edit its legal wording in place. A wording change requires a new version approved by Nicholas.

## Deployment settings

- Install LibreOffice Writer, Liberation Serif, and FreeSerif on every rendering worker. The template uses Liberation Serif for body text and FreeSerif for checkbox glyphs. Verify `fc-match -f '%{family}' 'Liberation Serif'` and `fc-match -f '%{family}' 'FreeSerif'` report those families.
- Set `LEASE_LANDLORD_SIGNER_NAME="Robert Wieler"` in every environment.
- Set `LEASE_LANDLORD_SIGNER_EMAIL="robert@connectionhomes.ca"` only in production. Set `LEASE_LANDLORD_SIGNER_EMAIL="nicholas@connectionhomes.ca"` and `LEASE_NONPRODUCTION_SIGNER_EMAIL="nicholas@connectionhomes.ca"` in development, test, and staging. The service requires both nonproduction settings to match, so an accidental production address cannot be used for a test envelope.
- Configure the existing DocuSign JWT, Box OAuth, MinIO, and Redis worker. `BOX_RENTAL_PROPERTIES_FOLDER_ID` must identify the existing `PRIVI/Rentals` folder; the service creates `{unit_address}/Leases` beneath it.
- Run Alembic revision `20261102_0055` and restart the backend, Celery worker, and beat. The beat schedule polls open envelopes every 15 minutes. The existing Change Orders DocuSign Connect webhook also queues completed lease processing.

## Schema additions

`lease_agreements`, `lease_agreement_events`, and `lease_agreement_tasks` are new tables. `rental_properties` gains `municipality`, `is_multiplex`, `is_condo`, and `lease_utility_override`. The agreement also keeps `recipient_status` to show which signing stage is pending and `draft_revision` to reject a preview made while another editor saved changes. Existing property, unit, tenancy, and tenant records remain the source of initial values.

## Manual acceptance before production merge

1. Open the Leases tab for 166 Clubhouse Drive and confirm municipality `Lorette`. Create a draft, preview the PDF, and verify the page layout and all DocuSign tabs with two internal test tenants.
2. With the nonproduction landlord signer set to Nicholas, send a test envelope. Verify no tenant receives it before landlord signature. Complete the envelope and verify the combined PDF and certificate under `PRIVI/Rentals/{unit_address}/Leases`.
3. Check `contact_form_data`, review before applying it to tenant records, and verify the Plooto PAD staff task. Void a separate open test envelope and verify resend only reaches pending recipients.
