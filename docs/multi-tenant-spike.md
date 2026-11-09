# Multi-tenant schema/auth spike

**Tenant ≡ Org.** `core.orgs` is the tenant table. `core.users.org_id` remains the user's home/default org for compatibility, while `core.user_org_memberships` is the source of truth for multi-tenant access. This spike seeds Potterstone Builders and PRIVI Holdings alongside the existing Connection Homes org.

| Org (slug) | Intended modules and ownership |
| --- | --- |
| Connection Homes (`connection-homes`) | Land, OTP, Projects/Tendering/construction, costbook for CH builds, sales/presales/funds as today. |
| Potterstone Builders (`potterstone-builders`) | Commercial construction projects: lots/projects under this org. Ordinary members see only projects to which they were created or invited as `project_members`. |
| PRIVI Holdings (`privi-holdings`) | Rentals, leases, and tenant operations, including maintenance on rental units. This ownership is planned; existing rental records are not moved by this spike. |

## Access model

`User.is_superadmin` bypasses tenant walls; the migration flags Nicholas by email if present. A normal user needs an explicit org membership. A `tenant_admin` can access every project in that org. A `member` needs a `core.project_members` row for the lot, with `owner > editor > viewer` access. Project ownership is derived from `lot.development_id → development.org_id`; projects in the UI are lots with a trigger type. Tender packages still key on `property_id`, so later tender authorization must resolve the associated lot and call the project helper.

The planned superadmin switcher sends `X-OfficeHub-Org` as an org slug or UUID. `resolve_current_org` checks the selected org and membership, and falls back to the user's home org when no header is present. The helper also checks membership for that fallback. These helpers are **not yet wired into every router**; they do not enforce isolation by themselves.

## Rollout

1. Land this schema, migration, helpers, tests, and documentation spike.
2. Apply the migration on staging first and verify seeded orgs, memberships, and the Nicholas flag. Apply to production only in a separately approved rollout.
3. Later, migrate rental table ownership to PRIVI, including maintenance relationships on rental units.
4. Add Potterstone Google login and invite UX; create a Potterstone org membership on invite acceptance, then create project memberships for assigned lots.
5. Enforce `require_project_access` on `/projects` and tender APIs, resolving tender `property_id` to its lot. Add tenant filtering to lists as well as individual reads/writes.
6. Add the UI tenant switcher after the APIs enforce tenant access.

## Non-goals

This spike does not move lots or rentals between orgs, rewrite all routers or middleware, change JWT or refresh-cookie behavior, implement Potterstone login/invitations, change lease wording, or turn on tenant isolation across the application. It does not apply the migration to a live database.
