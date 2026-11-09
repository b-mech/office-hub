# Location review: private workspace preview only

## Root cause
The historical Google rental script chose the first result without requiring
ROOFTOP / a matching civic address. The city default was Winnipeg even when
municipality said Lorette, Landmark or Grande Pointe. All 8 Clubhouse addresses
therefore shared the Winnipeg city centre; Landmark addresses resolved to the
wrong Winnipeg street. Unsuffixed Regent / Whittier addresses are ambiguous
between East and West. Reusing legacy pins is not safe.

## Schema and merge order
`20261109_0059` follows `20261106_0057` on PR #2. PR #3 separately has
`20261106_0058`; before both are deployed, add an Alembic merge revision with
both heads (do NOT renumber or blindly run `upgrade head` across two heads).
No production or staging database was migrated.

Location storage is on `core.lots`, not `core.properties`: only 46 of the
153 preview lots have property_id; land inventory must not acquire fabricated
financing property identities just to show a map. Rental metadata is on
`rental_properties`. New nullable columns hide unverified legacy pins until
an operator explicitly re-geocodes them.

## Operator workflow
Back up the target database with pg_dump first. The script currently has a hard
preview-database guard; a production rollout requires a separately reviewed
change to that guard, a backup and explicit approval.

From backend (using a venv with SQLAlchemy, asyncpg, python-dotenv):

```sh
python scripts/geocode_locations.py --env-file /path/to/preview.env \
  --database officehub_workspace_qa_20261106 --force --dry-run \
  --cache /private/geocode_cache.json --csv /private/geocode_review.csv
# Review CSV, then repeat without --dry-run. Cached responses are reused.
# For later gaps, use --only-missing instead of --force.
```

`--force` ignores every stored coordinate. `--dry-run` never updates the DB;
it still caches public responses and writes the review CSV. Only house-number
AND street AND community matches count as house precision. Street matches are
approximate, shown with hollow dashed markers and individually listed for
manual pin placement. Shared points are downgraded, never jittered or treated
as exact. Locality-only, street-mismatched and failed results have NULL coords.
Do not resolve missing East/West directions from the old coordinates.

Nominatim policy: https://operations.osmfoundation.org/policies/nominatim/
This is a small user-requested one-time batch, one host, one thread, >=1.1 sec
between requests, with persistent local cache and backoff for temporary 503s.
It is not a recurring geocoder, autocomplete, or a generic in-app API. Public
civic addresses only; no tenant names/contact information. Map and cached data
attribution: © OpenStreetMap contributors, ODbL. Keep CSV/cache out of git.

Community corrections are based on the existing development municipality,
plus verified settlement names: Parkview Pointe -> West St. Paul;
Wheatland Park -> Dugald; Mountain Ridge Park -> Stony Mountain;
Prairie View Lakes -> La Salle; Oak River Meadow -> Île-des-Chênes;
Sunset Acres -> New Bothwell. Clubhouse -> Lorette; Sand Piper -> Landmark.

Sources checked:
- https://www.ventura.mb.ca/home/communities/ (Prairie View, Oak River)
- https://adrproperties.ca/mountain-ridge-park (Stony Mountain)
- https://steinbachrealty.com/listing/7-acres-lane-new-bothwell-manitoba-r0a-1c0-29460621/
- https://mypropertyguide.ca/listings/384-sandpiper-trail-landmark
- https://www.rmtache.ca/p/business-directory

## QA acceptance
Backend precision tests, frontend partition tests, tsc and production build.
Browser check must inspect loaded tiles, markers, approximate legend, list
selection and popup; HTTP 200 / a build pass alone are not visual QA.
A house-level OSM result is not a survey or a guaranteed rooftop placement.
Missing/new subdivision coverage remains a manual review task.
