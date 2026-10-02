# Change Orders production gaps

Audit date: 2026-10-01 (America/Winnipeg)  
Production checkout: `/home/officehub/office-hub`  
Audit mode after source preservation: read-only, except for this report

No Celery process or other service was started, no queue was changed, and no request was made to DocuSign, Box, QuickBooks, Plooto, Gmail, or any other external integration. Integration readiness was determined from source, redacted configuration presence, token-file metadata, the local PostgreSQL database in a read-only transaction, and existing system logs.

## Production working-tree preservation

The production checkout began on `feature/docusign` at `6e227418`, seven commits ahead of `origin/feature/docusign`, with 61 modified tracked files and 70 untracked files. The complete staged diff contained 131 files, 13,200 insertions, 285 deletions, and no deletions. It comprised the presales, maintenance, financing, promotion, rental, Chrome extension, frontend, migrations, tests, documentation, and systemd work visible in the original status. No `.env`, token, database dump, editor backup, or other ignored runtime-secret file was added.

Everything in that status was preserved without alteration in:

- Branch: `ops/prod-uncommitted-2026-10-01`
- Commit: `0eeabf8` (`Snapshot production working tree changes`)
- Remote: `origin/ops/prod-uncommitted-2026-10-01`

The commit is the full diff: `git show --stat 0eeabf8` and `git diff 6e227418..0eeabf8` reproduce the complete pre-commit snapshot. Nothing was discarded. The working tree was clean after the push; this report is the only subsequent file write.

## Executive finding

Change Orders cannot currently complete the new production workflow. The UI and API orchestration exist, but each external leg is either unconfigured or structurally fragile:

1. DocuSign JWT authentication fails because the configured PEM is malformed. It is also pointed at the DocuSign demo environment.
2. Box filing is disabled because `BOX_UNFILED_FOLDER_ID` is absent; the code defines “configured” as client ID + secret + unfiled folder. A token file exists but its access token is expired.
3. QuickBooks has client credentials but is set to sandbox, has no OAuth token, has no explicit change-order item, and has a callback URL that does not match the implemented route.
4. Payment email has no usable SMTP credential.
5. Plooto is not integrated. An operator must create a request manually and paste an arbitrary HTTP(S) URL.
6. QBO invoice creation is a FastAPI in-process background callback, not Celery. DocuSign sending, signed-document sync, Box filing, and SMTP are request/webhook work. Only QBO payment reconciliation is a Celery task.
7. The current workflow requires a Plooto link for **every** change order, including “add to mortgage” and negative credit change orders. This conflicts with the two payment methods and blocks sensible processing.
8. The 13 existing records predate the new payment/QBO workflow. All 13 have `plooto_status=not_started`, `qb_invoice_status=not_created`, and no payment email. Their legacy sent/signed/complete states cannot be interpreted as proof that the new flow ran.

## Flow as currently built

### 1. Prepare for signature

The UI's “Send for Signature” button calls `POST /api/v1/change-orders/{id}/prepare-signature` through the Next.js server proxy. The API requires a customer email, changes the record to `awaiting_payment_link`, sets `plooto_status=awaiting_link`, commits, and returns.

- Execution: inline API/DB work.
- Celery: no.
- Side effect after the response: FastAPI/Starlette `BackgroundTasks` calls QBO invoice creation in the uvicorn process.
- Required local config: `OFFICE_HUB_API_KEY` for the frontend proxy; it is present.
- Current failure: the step rejects the first five drafts because they have no customer email. For eligible records it moves state successfully, but the subsequent QBO background callback cannot authenticate. A uvicorn restart after the response can also lose that callback.
- Logic gap: `prepare_for_signature` ignores `payment_method`; both add-to-mortgage and due-upon-receipt orders are forced into the Plooto-link stage.

### 2. QuickBooks invoice creation

After prepare-signature returns, `_create_qbo_invoice_background` opens a new DB session and calls `quickbooks.create_invoice`. It either uses stored customer/project IDs or queries up to 1,000 QBO customers and matches a project by normalized address. It uses `QBO_CHANGE_ORDER_ITEM_ID`, or otherwise picks the first active QBO Service item, then POSTs an invoice and records the returned IDs locally.

- Execution: FastAPI in-process background callback after the HTTP response.
- Celery: no. `change_orders.reconcile_qbo_invoices` is Celery, but it only polls already-created invoices and marks zero-balance ones paid.
- Required config/credentials: `QBO_CLIENT_ID`, `QBO_CLIENT_SECRET`, a matching public `QBO_REDIRECT_URI`, `QBO_ENVIRONMENT`, OAuth token/realm file, and preferably an explicit `QBO_CHANGE_ORDER_ITEM_ID`.
- Present: client ID and secret.
- Missing/wrong: `QBO_ENVIRONMENT=sandbox`; `.qbo_token.json` is absent; `QBO_CHANGE_ORDER_ITEM_ID` is absent; no customer cache exists. The configured redirect is `http://localhost:8000/api/qbo/oauth/callback`, while the implemented callback is `/api/v1/change-orders/qbo/oauth/callback` and production is reached through the public frontend/tunnel.
- Current failure: the first attempted QBO API operation raises “QuickBooks is not connected”; `create_invoice` catches it and writes `qb_invoice_status=synced_error`. None of the 13 records has reached this code since the new workflow was introduced, so all remain `not_created` with no error text.
- Reliability gap: the QBO POST and local commit are not atomic. If QBO creates the invoice and the process dies before the local ID is committed, retry can create a duplicate because there is no QBO-side idempotency key or lookup by Office Hub change-order ID.
- Data gap: negative totals would be sent through the same invoice path even though they likely require a credit memo or no QBO transaction.

### 3. Plooto payment request

The UI instructs the operator to create a funds request manually in Plooto and paste its link. `POST /payment-link` validates only that the value is an HTTP(S) URL, stores it, sets `plooto_status=link_received`, commits, then immediately calls DocuSign.

- Execution: manual work in Plooto followed by an inline API call.
- Celery: no.
- Required app credentials/config: none; Office Hub has no Plooto API integration.
- Present/missing: no Plooto credential or webhook is expected by the current code. No hostname allow-list or remote request/status verification exists.
- Current state: zero of 13 records has a Plooto link.
- Current failure/gap: Office Hub cannot create, inspect, reconcile, or prove payment of a Plooto request. Any HTTP(S) URL is accepted. Add-to-mortgage orders and credits are incorrectly blocked on this manual step.

### 4. DocuSign send and signature

After a Plooto link is saved, `send_to_docusign` renders the PDF and awaits `send_for_signature` in a worker thread. The DocuSign SDK obtains a JWT token and sends an envelope with signature/date anchors. On success Office Hub stores the envelope ID and sets status `sent`.

Signature completion has two paths:

- DocuSign Connect can POST XML to the public webhook. The webhook marks the record signed, downloads the combined PDF, files it in Box, and attempts the payment email.
- While the Change Orders page is open, the frontend POSTs `/sync-signed` for every locally `sent` order immediately and every 30 seconds. That endpoint tries to download the combined PDF; if it gets one, it marks signed, files it in Box, and attempts the email.

Execution is inline/awaited HTTP or webhook work (with selected blocking calls moved to threads). No part is a Celery task.

Required config/credentials:

- DocuSign integration key, impersonated user ID, account ID, RSA private key, JWT user consent, matching auth host/rest base, and a DocuSign Connect webhook pointing to the public Office Hub webhook.
- A webhook HMAC secret is required for a secure production endpoint, though the current code treats an empty secret as “accept every signature.”

Production state:

- Integration/user/account/keypair IDs and `DOCUSIGN_PRIVATE_KEY` are set.
- The private key fails an offline PEM parse. Existing backend logs on 2026-09-15 show repeated `DocuSign JWT authentication failed: Could not parse the provided public key` while the UI polled the four sent records.
- Auth host and REST API point to DocuSign demo (`account-d.docusign.com`, `https://demo.docusign.net/restapi`), not production.
- Test-recipient overrides are absent, so a successful send would target the change order's customer email.
- `DOCUSIGN_WEBHOOK_SECRET` is absent. The webhook therefore accepts unsigned/unauthenticated payloads.
- Whether DocuSign Connect is configured with the correct public `/backend-api/api/v1/change-orders/webhook/docusign` URL cannot be determined locally.

Current failure: both new envelope creation and signed-document retrieval fail at JWT authentication. `send_for_signature` turns the SDK error into no envelope and the API returns a 502. `get_signed_pdf` also returns `None`; `/sync-signed` masks that authentication failure as HTTP 200 with “not ready yet,” so the UI continues polling and the records remain sent.

### 5. Box filing

Viewing a draft PDF attempts to upload/update an unsigned PDF. Editing a draft that already has a Box file attempts to update it. After signature, the webhook or manual sync attempts to upload the signed PDF. The service searches for `1C - {address} - Change Orders`; unsigned PDFs go in `To Be Signed`, and signed PDFs go in the change-order folder. If the address folder is absent, it falls back to an unfiled folder.

- Execution: inline API/webhook work; some calls use `asyncio.to_thread`, while the PDF and manual-sync paths call Box synchronously from async endpoints.
- Celery: no.
- Required config/credentials: Box client ID/secret, public OAuth redirect, token file with refresh token, and `BOX_UNFILED_FOLDER_ID` under the current configuration predicate.
- Present: client ID, client secret, and a mode-0600 token file containing access and refresh tokens.
- Missing/wrong: `BOX_UNFILED_FOLDER_ID` is absent, so `settings.box_configured` is false and **all** `file_change_order_pdf` calls return without contacting Box, even if the correct address folder exists. The access token expired on 2026-09-14; the SDK could refresh it from the refresh token only after Box is considered configured. `BOX_REDIRECT_URI` is still `http://localhost:8000/api/v1/box/oauth/callback`, which is unsuitable for a normal production browser OAuth flow.
- Current failure: Box filing is skipped as “not configured or authenticated.” Local Box IDs on six legacy records show prior filing, not current connectivity; external file existence was not checked.
- Reliability gap: webhook exceptions are logged and swallowed, and the webhook still returns success, so DocuSign will not retry a failed Box operation. There is no durable retry queue or explicit Box failure field.

### 6. Payment email

After a signed PDF sync/webhook, `send_payment_email` sends a Gmail SMTP message containing the Plooto link, then writes `payment_email_sent_at`.

- Execution: awaited from the webhook/manual sync; SMTP itself runs in a thread.
- Celery: no.
- Required config/credentials: sender email plus `GMAIL_SENDER_APP_PASSWORD`, or an IMAP password only when `IMAP_USER` equals the sender.
- Present: the default sender is `yana@connectionhomes.ca`; an unrelated IMAP password is set for `docs@yourcompany.com`.
- Missing: `GMAIL_SENDER_APP_PASSWORD`. The IMAP fallback does not apply because the usernames differ.
- Current failure: any eligible send raises “GMAIL_SENDER_APP_PASSWORD is not configured for yana@connectionhomes.ca.” The webhook/manual-sync caller catches and logs the exception, leaving the order signed with no retry marker. All 13 have `payment_email_sent_at=NULL`.
- Logic gap: email eligibility is based only on the presence of a Plooto link, not `payment_method` or a positive amount.

### 7. Payment reconciliation and completion

Celery beat schedules `change_orders.reconcile_qbo_invoices` daily at 09:30 and 15:30 America/Winnipeg. It reads local records in QBO status `created`, GETs each QBO invoice, and marks zero-balance invoices `paid`.

- Execution: Celery worker task.
- Current failure: no worker or beat has ever run, and zero records have a QBO invoice, so there is currently nothing to reconcile.
- Workflow gap: nothing automatically changes a paid/signed order to `complete`. The pipeline permits users to move statuses manually through a generic endpoint without checking DocuSign, QBO, Plooto, email, or payment method. The two existing `complete` records are therefore manual state, not end-to-end evidence.

## State of all 13 change orders

This table reports only local PostgreSQL state. “Box yes” means a local Box file ID exists; it does not assert that the external file is still accessible. All records are unarchived. All 13 have QBO `not_created`, Plooto `not_started` with no link, and no payment email.

| # | ID | CO / address | Amount / method | Local progress | Missing or inconsistent |
|---:|---|---|---|---|---|
| 1 | `ca5901ef-fc71-44c2-b090-55d4292cf9bd` | CO-20260514-001 — 154 Ramona Gallos Way | $4,189.50 / add to mortgage | Draft; 19 lines | No customer email, envelope, Box file, QBO invoice, or payment artifacts. Duplicate of #2; choose a canonical record before action. Add-to-mortgage should not require Plooto. |
| 2 | `6529fc18-bd02-4ce8-8e1d-f4b5ffa6ab5b` | CO-20260514-001 — 154 Ramona Gallos Way | $4,189.50 / add to mortgage | Draft; 19 lines | Same content/state as #1, created six seconds later. Do not process both. |
| 3 | `dc0ab73f-d537-4c88-8d26-4c6f610ab5d7` | CO-20260520-001 — 27 Hester Park Cove | $99.75 / add to mortgage | Draft; 4 lines | No customer email or downstream artifacts. Duplicate of #4; choose a canonical record. |
| 4 | `702a5489-32ee-474c-ba38-3df41cca4f10` | CO-20260520-001 — 27 Hester Park Cove | $99.75 / add to mortgage | Draft; 4 lines | Same content/state as #3, created five seconds later. Do not process both. |
| 5 | `9696b81b-9235-43cf-bcf2-020af88b28cc` | CO-20260520-001 — 101 Lynne Lane | $13,443.68 / due upon receipt | Draft; local Box file; 28 lines | No customer email, envelope, Plooto link, QBO invoice, or email. This is the clearest positive-value candidate for the intended pay-now flow after config is repaired. |
| 6 | `1c08a0f1-33fe-4e02-9101-e010bceb3819` | CO-20260526-001 — 27 Hester Park Cove | $357.00 / add to mortgage | Manually `complete`; customer email | No envelope, Box file, QBO invoice, Plooto, or payment email. Duplicate business key/content with #7; `complete` is unsupported by integration evidence. |
| 7 | `bdc34180-aa22-437b-a4b7-ef39a99f1699` | CO-20260526-001 — 27 Hester Park Cove | $357.00 / add to mortgage | `sent`; envelope; local Box file; customer email | Duplicate of #6. DocuSign status cannot currently sync because JWT parsing fails. Do not resend until the existing envelope is reconciled. No QBO invoice. |
| 8 | `0ca3359e-5fd7-44fb-88bd-392e1bb2f929` | CO-20260522-001 — 154 Ramona Gallos Way | **-$262.50** / add to mortgage | Manually `complete`; envelope; local Box file; customer email | No QBO evidence. A negative change order must not enter the ordinary invoice/Plooto-payment path; define credit handling and verify the legacy envelope before accepting `complete`. |
| 9 | `53ec096d-f933-4c61-bd84-7e79539d04fa` | CO-20260609-001 — 101 Woodland Way | $9,547.65 / add to mortgage | `sent`; envelope; customer email | No Box file or QBO invoice. Existing envelope sync is blocked by the malformed DocuSign key. Reconcile, do not blindly resend. |
| 10 | `a0eab2fe-38a0-4f1b-8c84-5a6b3ba8f964` | CO-20260611-001 — 27 Hester Park Cove | $357.00 / add to mortgage | `sent`; envelope; local Box file marked unfiled; customer email | Reconcile existing envelope after DocuSign repair, then move the Box file to/confirm the correct address folder. No QBO invoice. |
| 11 | `dfc89798-a0a4-4adb-84c9-404c565c4051` | CO-20260615-001 — 675 Community Row | $1,139.25 / due upon receipt | `sent`; envelope; customer email | Legacy state has no Plooto link despite being sent, plus no Box/QBO/email. Reconcile the existing envelope first; do not create a second envelope merely to satisfy the new link-first workflow. |
| 12 | `3e424e0e-e490-40fd-8137-216c7bc237b1` | CO-20260730-001 — 10 Deer Meadow Run | $2,730.00 / add to mortgage | `signed`; envelope; local Box file; customer email | Signature/Box appear complete locally. No QBO invoice. No Plooto/email is appropriate if add-to-mortgage is confirmed, but the current code has no such branch and completion remains manual. |
| 13 | `00f5e773-5bd7-4085-8cef-80c6118257ec` | CO-20260731-001 — 52 Ash Cove | **-$1,038.45** / due upon receipt | `signed`; envelope; local Box file; customer email | A negative “due upon receipt” record should not request payment or send a Pay Now email. Define whether this is a credit memo/refund, correct the payment method/state, and keep it out of ordinary QBO invoice creation. |

Summary:

- Statuses: 5 draft, 4 sent, 2 signed, 2 complete.
- Customer email: 8 present, 5 missing.
- DocuSign envelope: 7 present.
- Local Box file ID: 6 present; one is marked unfiled.
- QBO invoice: 0 created, 0 paid, 13 not created.
- Plooto link: 0.
- Payment email: 0.
- Duplicate business keys: three pairs (#1/#2, #3/#4, #6/#7).
- Negative totals needing a separate credit rule: #8 and #13.

The database Alembic version is `20260917_0045`. The snapshot also contains unapplied maintenance migrations 0046 and 0047; those are unrelated to Change Orders but matter to any future deployment plan.

## Proposed fix order

### P0 — prevent unsafe or duplicate external writes

1. Keep Change Order send/retry controls operationally frozen until the workflow branches and credentials below are corrected. In particular, do not resend the four `sent` envelopes and do not bulk-create QBO invoices.
2. Reconcile the three duplicate pairs with the business owner and select one canonical record in each pair. Archive/merge only in a separately approved data-cleanup operation; this audit discarded nothing.
3. Encode payment-method rules before enabling integrations:
   - `add_to_mortgage`: no Plooto link and no Pay Now email; define whether/when QBO should receive an invoice.
   - positive `due_upon_receipt`: Plooto link required, then signature, then payment email.
   - zero/negative total: no ordinary Plooto payment request or positive QBO invoice; implement an explicit credit/no-charge path.
4. Replace unrestricted status mutation with guarded transitions. `complete` should require the business evidence appropriate to the method instead of being a free-form pipeline move.

### P1 — make orchestration durable and idempotent

5. Move QBO creation, DocuSign send/sync, Box filing, and payment email into explicit durable jobs (or an outbox-driven workflow) with per-step states, attempts, last errors, and timestamps. A FastAPI post-response callback and swallowed webhook errors are not sufficient for financial/document delivery.
6. Add idempotency before retrying external writes:
   - QBO: persist an attempt/idempotency key before POST and recover by Office Hub change-order ID/private note before creating again.
   - DocuSign: never create a second envelope when an envelope ID already exists unless a deliberate void/resend operation is recorded.
   - Email: retain `payment_email_sent_at`, but also record failures and make retry explicit.
   - Box: record unsigned/signed file IDs separately and persist filing errors; do not overwrite provenance with one shared field.
7. Make the webhook secure and retryable. Require a configured HMAC secret, reject unsigned requests, and enqueue completion handling only after validating/parsing the event. Return failure when durable acceptance fails.

### P2 — repair configuration, without exercising it yet

8. DocuSign:
   - replace the malformed private key with a parsable RSA private key matching the integration key;
   - decide demo versus production and make integration key, account, auth host, and REST base consistent;
   - confirm JWT impersonation consent;
   - configure the public Connect URL and a webhook HMAC secret;
   - keep test-recipient overrides explicit and empty for production.
9. Box:
   - set `BOX_UNFILED_FOLDER_ID` or change `box_configured` so a missing fallback does not disable filing to known address folders;
   - set a public OAuth redirect URI;
   - reauthorize/refresh only in a controlled test and verify target folder permissions;
   - fix synchronous Box calls in async routes.
10. QuickBooks:
   - decide sandbox versus production before authorization;
   - correct the public callback to the implemented route;
   - perform OAuth authorization later under an approved test plan and protect the token file;
   - configure an explicit change-order item instead of selecting the first Service item;
   - validate address-to-project mappings for the canonical records before invoice creation.
11. Email: provision a Gmail app password for the configured sender (or use a managed mail provider), then add a safe recipient-override/dry-run mechanism. Do not rely on the unrelated IMAP credential.

### P3 — controlled data recovery and rollout

12. Backfill/verify customer emails for the five missing-email drafts. Resolve duplicates and negative-total semantics first.
13. After DocuSign auth is repaired, read the seven existing envelope states and download/file signed documents without sending new envelopes. Reconcile #7, #9, #10, and #11 first because they are locally `sent`.
14. Verify the six local Box references and move/re-file #10 from unfiled. Do not assume a local Box ID proves current access.
15. Create a reviewed QBO candidate list only after canonicalization and payment-method rules. Start with one positive, signed, nonduplicate record in the intended environment; verify the local ID and QBO invoice before proceeding one at a time.
16. Test one positive due-upon-receipt order end to end using controlled DocuSign, Box, QBO, Plooto, and email recipients. Confirm every state/error is observable before wider rollout.
17. Only then deploy/start the separate Celery worker and single beat instance, after following the broker cleanup safeguards in the Celery startup audit. Monitor queue depth, task IDs, retries, external IDs, duplicate creation, and state transitions through the first scheduled QBO reconciliation.

The safest first production repair target is not one of the legacy records. Use a purpose-built controlled change order after P0–P2 are complete, then recover the 13 records individually from their existing external IDs and local evidence.
