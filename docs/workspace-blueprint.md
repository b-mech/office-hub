# Workspace blueprint: Projects, Clients, Rentals, tenant scope

Status: approved direction, **docs only**. Builds on `docs/multi-tenant-spike.md` (migrations `20261102_0055`, `20261105_0056`). This doc adds no migration, route, or UI. It is grounded in the code at `feature/lease-tenant-integration` @ `d390b0a`.

## 1. Terms used in the code today

| Term in the product | What it is in the code |
| --- | --- |
| **Org / tenant** | `core.orgs` (`connection-homes`, `potterstone-builders`, `privi-holdings`). Access: `core.user_org_memberships` (`tenant_admin`/`member`), `User.is_superadmin`. |
| **Lot** | `core.lots` row. The org comes from `lots.development_id → core.developments.org_id`. `core.lots` has no `org_id`. |
| **Project** | A **lot** with `trigger_type IS NOT NULL AND cancelled = false` (`otp`/`spec`/`showhome`). There is **no projects table**. `GET /api/v1/projects` (`modules/lots/router.py::list_projects`) returns `LotOut` for those lots. `GET /api/v1/lots` returns the rest (`trigger_type IS NULL OR cancelled`). Detail for both is `GET /api/v1/lots/{lot_id}`. Activation is in `services/lot_activation.py`. |
| **Project ACL** | `core.project_members(lot_id, user_id, role owner/editor/viewer)`. The helpers are `core/tenancy.py::require_project_access`, `resolve_current_org`, and `has_org_access`. **No router calls them yet.** |
| **Property** | `core.properties` (address registry, `property_type` default `lot`). A lot links through `lots.property_id` (unique when set). This is **not** a rental property. |
| **Tendering** | `core.tender_packages.property_id → core.properties`, plus `documents.tender_documents`, `documents.tender_document_markups`, `core.tender_bids`, `documents.tender_bid_documents`, and `core.tender_awards`. Routes are in `routers/tendering.py` under `/api/properties/{property_id}/tender-packages`, `/api/tender-packages/*`, `/api/tender-documents/*`, `/api/tender-document-markups/*`, and `/api/tender-bids/*`. The UI is `TenderPackagesPanel` inside `LotWorkspace` on `/projects` only (`showTendering`). |
| **Contractors** | `core.contractors` and `core.contractor_categories` (`/api/contractors`). They are global, with no `org_id`. |
| **Client / buyer (today)** | Not a first-class record. Buyers are `core.contacts` (`org_id`, `contact_type` buyer/developer/realtor/vendor/lawyer) linked to a lot through `sales.parties(party_role buyer/co_buyer/…) → sales.agreements.lot_id`. The OTP timeline `client_name` comes from those buyer parties. `sales.change_orders.client_name/customer_email` is free text. |
| **Change orders** | `sales.change_orders`, at `/api/v1/change-orders` (X-API-Key). **Gotcha:** `change_orders.lot_id` is an FK to `land.agreements.id`, not `core.lots.id`. |
| **Costbook** | Schema `costbook` (budgets, lines, POs, invoices, vendors) at `/api/v1/costbook`. `budgets.org_id` is NOT NULL. `budgets.lot_agreement_id` points to `land.agreements` (no FK). The UI is `/costbook` and `/lots/{lotId}/costbook` (`/lots/{lotId}` redirects there). |
| **Documents** | `documents.documents` (`org_id`, MinIO key) feeds land and sales agreements. There is no `lot_id`. Tender, lender, funds, and maintenance files have **their own tables**. There is no single shared document table yet. |
| **Lifecycle (lot)** | `LotStatus`: `land_contracted, land_purchased, serviced, sale_signed, build_active, possession, warranty`, plus `possession_confirmed_date`. |
| **Rentals** | Tables in the `public` schema with integer ids and **no org columns**: `rental_companies` ← `rental_properties` ← `rental_units` ← `rental_leases` (+ `rental_lease_tenants`, `rental_tenants`). `lease_agreements` holds DocuSign leases (UUID), `lease_agreement_tasks`, inspections, and lease-import batches. Maintenance is in `maint_tickets` (property/unit/lease) and `maint_work_orders`. |
| **Dashboard** | None. `/` redirects to `/documents`. `/financing` has a financing dashboard. |

Current sidebar (`frontend/src/app/layout.tsx`, duplicated in `MobileNavigation.tsx`): Documents, Lots, OTP Timeline, Projects, Change Orders (`/projects/change-orders`), Costbook, Financing, Presales (`/financing/presales`), Contractors, Lenders (`/financing/lenders`), Rentals, Lease Import, Inspections, Inspection Reports, Settings.

**Rule:** the new "Project" concept means the existing **project lot**. Do not create a parallel `projects` table. Do not pair the Project UI with `/api/v1/lots` (that is the land list).

## 2. Target navigation (regroup, not rewrite)

Keep every route URL that exists today. Change only grouping, labels, and visibility. Define the nav once in a shared config, so `layout.tsx` and `MobileNavigation.tsx` stop diverging.

- **Dashboard** `/` (new, replaces the redirect)
- **Clients** `/clients` (new), with `/clients/{client_id}`
- **Projects** `/projects`, with project workspace `/projects/{lot_id}` (new detail route on the **lot id**) and tabs:
  - Overview: `LotOut` fields, status, possession
  - Tendering: existing `TenderPackagesPanel`, using `lot.property_id`
  - Change Orders: existing list, filtered to the project where the join is reliable
  - Costs: existing `/lots/{lotId}/costbook` content, so the name "Costbook" stays
  - Financing/Presales: links to the existing `/financing/presales/{lotId}`
  - Tabs a project's data cannot support are hidden, not stubbed.
- **Land** (CH only): Lots `/lots`, OTP Timeline `/lots/timeline`, Documents `/documents`, Presales, Lenders, Financing
- **Contractors** `/contractors`, under Projects as the tendering directory
- **Rentals** `/rentals` (Overview, new) → Properties/Map (the current `/rentals` map moves to `/rentals/map`), Leases, Lease Import, Inspections, Inspection Reports
- **Settings** `/settings` (Imports, Users, Presales)

Tendering is never top-level. Clients and Projects are two views of one record: a client page lists its project lots and links to `/projects/{lot_id}`. Both use the same id, so deep links stay single-record.

**Visibility by org**, derived from the API rather than hard-coded per tenant:
- CH: Dashboard, Clients, Projects, Land, Contractors, Settings, plus Rentals while rentals are unowned (see §5).
- Potterstone: Dashboard, Clients, Projects (assigned only). No Land.
- PRIVI: Dashboard, Rentals.
- Superadmin: everything, plus a later org switcher.

Hiding a nav item is for usability only. The API is the security boundary.

## 3. Shared data model (first release)

### `core.clients` (new)
| Column | Notes |
| --- | --- |
| `id` uuid pk | |
| `org_id` uuid NOT NULL FK `core.orgs` | owner tenant; immutable after create |
| `client_type` text check `individual`/`company` | |
| `display_name` text NOT NULL, `name_normalized` text NOT NULL | Index `(org_id, name_normalized)`, **not unique**, because two clients can share a name. Duplicates are flagged in the UI. |
| `primary_contact_id` uuid NULL FK `core.contacts` | Contact details stay in `core.contacts`. No JSON contact blob. Same-org is enforced (see below). |
| `lifecycle_stage` text check `lead`/`qualified`/`active`/`possession`/`warranty`/`closed`/`lost` | Default `lead`. |
| `stage_changed_at` timestamptz | |
| `external_ref` text NULL | For a later external CRM. Unique on `(org_id, external_ref)` when not null. |
| `notes` text, `created_at`, `updated_at`, `created_by` FK users | |

Same-org integrity: `core.lots` has no `org_id`, and `core.contacts` does. A composite FK `(primary_contact_id, org_id) → contacts(id, org_id)` needs a unique `(id, org_id)` on contacts, which is cheap to add. For lots, enforce the rule in the service layer (`client.org_id == development.org_id`) **and** with a DB trigger on `core.lots.client_id`, so no route can link a client and a project across tenants. Cross-tenant sharing is out of scope until there is an explicit share design.

### `core.lots.client_id` (new, nullable)
- FK `core.clients`, `ON DELETE RESTRICT`, indexed.
- One main client per project lot. Additional parties (co-buyer, realtor) keep using `sales.parties`. Add a `client_project_roles` table only when a real need for several clients on one project appears.
- Only meaningful for project lots. The API rejects setting it on non-project lots.
- **Backfill: none.** Existing CH lots keep `client_id = NULL`. A later admin-reviewed "suggest from buyer party" tool may propose links from `sales.parties` (`buyer`, `is_primary`), but nothing is linked automatically.

### Lifecycle history
First release: `lifecycle_stage` and `stage_changed_at` on `core.clients`, with each change written to the existing `core.audit_log` (`schema_name='core', table_name='clients'`, old/new data). A dedicated `client_stage_history` table is deferred until reporting needs it.

`Lot.status` is **not** extended with lead/qualified. A lead has no lot yet. Possession and warranty for the build stay on `LotStatus`. Warranty and service work later goes in its own table (§6). It does not get pushed into lot status.

### Lot org identity
Keep the derivation `lot → development.org_id`, which is the same as `require_project_access`. Do not add `lots.org_id` in release 1. Every existing lot already has a CH development, so no backfill is needed.

Potterstone constraint to remember: a project lot needs a development and a **globally unique** `legal_description_normalized`. Creating Potterstone commercial projects may need that uniqueness scoped per org. That is decided in the Potterstone stage, not now.

### Migration plan (future PR, not this one)
One Alembic revision after `20261105_0056`:
1. Create `core.clients` and its indexes.
2. Add unique `(id, org_id)` on `core.contacts`.
3. Add nullable `core.lots.client_id`.
4. Add the trigger that checks client org = lot development org.
5. Add `core.orgs.member_project_scope` (§4).

It is idempotent-safe (adds only, no data rewrite except the step 5 default), has a reversible `downgrade`, and is rehearsed on a fresh prod copy like PR #2. Apply it to staging before prod.

## 4. Access enforcement (first release)

- **Request user:** tenant-scoped routes require `request.state.user` and return 401 without it. Today `AuthenticationMiddleware` lets `/api/*` through anonymously when `AUTH_ENFORCED=false`, except `/api/rentals/leases`. Confirm prod runs with `AUTH_ENFORCED=true`, or move these routes behind `current_user`, before enabling ACLs.
- **Org selection:** `resolve_current_org` handles the optional `X-OfficeHub-Org` (slug or UUID). With no header it uses the home org, which keeps CH backward compatible. An unknown org returns 404. An org without membership returns 403. The header only selects a view. Ownership on writes always comes from the parent object (`lot → development.org_id`, `client.org_id`), never from the header or the request body.
- **CH compatibility:** migration 0056 maps CH non-admin users to `member`. Under `require_project_access` they would lose every project that has no `project_members` row. Add `core.orgs.member_project_scope` with values `org` | `assigned`, default `assigned`, and backfill `connection-homes = org`. With `org`, a member gets viewer/editor access to all of the org's projects. Editor is used unless `users.role = readonly`. With `assigned`, which applies to Potterstone, a member needs `project_members`.
- **Lists:** `/api/v1/projects`, `/api/v1/lots`, `/api/v1/lots/timeline`, and `/clients` filter in SQL to accessible orgs and lots. A Potterstone member with no `project_members` rows gets `[]`, not everything.
- **Detail and children:** `GET /api/v1/lots/{lot_id}`, hold/cancel, and every tender route resolve the owning lot (`tender_packages.property_id → lots.property_id`). Document, markup, and bid routes go child → package → property → lot. Each then calls the project check. Inaccessible objects return 404 for lists and children (so existence does not leak) and 403 on an explicit org switch.
- **Global tables:** contractors and contractor categories stay CH and superadmin-only until they get an `org_id`.
- **Logging:** authorization failures log user id, org id, and object id only. They never log tokens, cookies, or headers.

## 5. Rentals overview (`/rentals`)

Rental tables have no org column. Until the PRIVI ownership migration lands, the overview is visible to superadmin and to the org(s) that own rentals today. The cheapest bridge is a `rental_companies.org_id` column (later stage), because every `rental_properties` row already has `company_id`.

Metrics from **existing fields only**:
| Card | Source |
| --- | --- |
| Occupancy | Units with a `rental_leases.status IN ('active','month_to_month')` lease over all `rental_units`. `rental_units.status` defaults to `unknown` and is not maintained, so it is not used. |
| Rent roll | Sum of `rent - coalesce(rent_discount_amount,0)` on active leases. This is the **scheduled** rent, not a collected amount. |
| Leases awaiting signature | `lease_agreements.status IN ('sent','delivered')`. Drafts are `status='draft'`. |
| Post-signing follow-ups | `lease_agreement_tasks.status='open'` (Plooto PAD setup). |
| Upcoming renewals | Active leases with `lease_end` in the next 60/90 days, plus `month_to_month` leases. |
| Maintenance needing attention | `maint_tickets.status NOT IN ('resolved','closed','cancelled','duplicate')`, grouped by priority (`emergency/urgent/routine/low`). |
| Inspections | The existing `/api/rentals/properties/map` status (current/due/overdue/never). |

**Not available, so not shown:** rent payment or arrears status. No payments model exists. Adding one (for example from a Plooto or QuickBooks feed) is a separate model addition. A "lease approval" status also does not exist beyond draft → sent → delivered → completed/voided.

## 6. Dashboard (`/`)

The dashboard replaces the `/documents` redirect and uses existing styling. It shows only cards with real data, scoped to the resolved org and the user's access:
- **Active projects:** count and list from the `/api/v1/projects` query, grouped by `LotStatus`.
- **Tenders needing action:** `tender_packages.status IN ('draft','sent','bids_in','compared')`, ordered by `due_date`. This needs one new org-scoped list endpoint, because today packages are only listed per property.
- **Upcoming milestones:** `/api/v1/lots/timeline` (OTP/land events, CH), `land.milestones.expected_date`, and `possession_confirmed_date`.
- A rentals summary card is shown to orgs with Rentals access.

Client activity and warranty cards are added only once those tables exist.

## 7. First release (scope)

1. Migration from §3 and §4 (`clients`, `lots.client_id`, `orgs.member_project_scope`), rehearsed on a fresh prod copy.
2. API:
   - `/api/v1/clients`: list, create, detail, patch stage. Org from `resolve_current_org`.
   - Set or clear a client on a project lot.
   - ACL enforcement on projects, lots, timeline, and all tender routes.
   - Org-scoped tender-needs-action list.
   - Rentals overview summary endpoint.
3. UI:
   - Shared nav config with permission-based sections.
   - `/clients` list and detail.
   - `/projects/{lot_id}` workspace with tabs that reuse `TenderPackagesPanel` and costbook content.
   - `/rentals` overview (map moves to `/rentals/map`).
   - `/` dashboard.
   - No visual redesign.
4. Not included: invites, the org switcher UI, rental org migration, warranty/service, and CRM follow-ups.

### Acceptance criteria
- The existing suite stays green (228 backend tests at `d390b0a`), plus new tests.
- Negative cross-tenant tests: a Potterstone member cannot list, read, or modify a CH project lot, tender package, tender document content, markup, bid, or award, or a CH client. Lists return `[]` or omit the rows. Direct ids return 404 or 403.
- A Potterstone member with zero `project_members` gets an empty project list, not all projects.
- A CH member with zero `project_members` keeps today's access (`member_project_scope=org`). CH `readonly` users stay read-only.
- A Potterstone member sees only their owned or invited project lots, and an `editor` or `viewer` role is respected on writes.
- A superadmin sees all orgs. `X-OfficeHub-Org` with an unknown value returns 404, and a non-member org returns 403. No header defaults to the home org.
- Linking a client to a lot in another org fails at both the API and the DB trigger. Setting `client_id` on a non-project lot is rejected. `primary_contact_id` from another org is rejected.
- No route derives write ownership from a header or the request body.
- Logs contain no tokens or cookies.
- Prod is unchanged until a separately approved deploy.

## 8. Later stages
1. **CRM:** lead capture, follow-up tasks (could reuse the `core.reminders` pattern), stage history table, and a buyer-party link suggestion tool.
2. **Possession, warranty, and service:** a `service_requests` table linked to client and lot. It could reuse patterns from the `maint_*` intake and work-order design without sharing the rental tables.
3. **Potterstone:** Google login, invites, project membership on accept, the org switcher UI, and org-scoped legal-description uniqueness. This comes only after the §4 enforcement ships.
4. **Rentals ownership:** `rental_companies.org_id` (or org on properties), PRIVI backfill, tenant-scoped rentals, lease, maintenance, and inspection routes, then the PRIVI rollout.
5. **Shared documents:** converge per-feature file tables onto `documents.documents` with owner links. This is separate work.
6. **Reports, archive, dedup, and AI assistant reports:** separate tracks (`feature/ai-assistant-reports`), not assumed here.
7. `contractors.org_id` and tenant-scoped contractor directories.
