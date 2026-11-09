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
both current heads, `20261106_0058` and `20261109_0061` (draw-history
followup to manual-pin 0060). Do NOT merge the obsolete 0059 head, renumber, or blindly
run `upgrade head` across two heads.
No production or staging database was migrated.

Location storage is on `core.lots`, not `core.properties`: only 37 of the
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

## Preview result (Nov 9, 2026; America/Winnipeg)

| Portfolio | House-level | Street approximate | No acceptable result |
|---|---:|---:|---:|
| Rentals | 2 | 13 | 6 |
| Lots | 0 | 56 | 97 |

All 21 rentals and all 153 lots were re-geocoded in the private preview only.
House matches: 59 Guay Avenue, 136 Bank Avenue. Clubhouse is now in Lorette,
Sand Piper is in Landmark, and Froese is Headingley. Regent (311/313/315)
and Whittier (389/391) need East/West confirmation rather than trusting an
old pin. GPM condo 79-100 was withheld because OSM returned the wrong town.
All 153 lots and the other 19 rentals still need an exact manual parcel pin;
56 lots and 13 rentals have clearly labelled approximate street positions.

Broad community spot-checks (not a parcel survey):

| Address | Expected community | Result |
|---|---|---|
| 59 Guay Avenue | Winnipeg | House; 49.871607, -97.108522 |
| 136 Bank Avenue | Winnipeg | House; 49.861369, -97.100089 |
| 142 Clubhouse Drive | Lorette | Street; 49.746883, -96.894367 |
| 61 Sand Piper | Landmark | Street; 49.672253, -96.813744 |
| 90 Froese Crescent | Headingley | Street; 49.814557, -97.351364 |
| 407 Country Vista Drive | La Salle | Street; 49.684785, -97.265133 |
| 23 Morning Glory Way | Dugald | Street; 49.879126, -96.834275 |
| 215 Middlechurch Gate | West St. Paul | Street; 49.980809, -97.088781 |
| 113 Blossom Way | West St. Paul | Street; 49.982640, -97.081701 |
| 150 Rosybloom Lane | Île-des-Chênes | Street; 49.705057, -96.988510 |
| Sunset Drive, Lot 1 | New Bothwell | Street; 49.589897, -96.902717 |
| 177 Ramona Gallos Way | Winnipeg | Street; 49.961099, -97.154431 |

Backend: 242 passed, 18 skipped, 2 subtests passed. Frontend: 7 unit tests,
`tsc --noEmit`, build and client API URL check passed. HTTP checks: both map
pages, rental map API, tenant lots/projects APIs and /backend-api/health 200.
Chrome screenshots on Nicholas's Mac show loaded OSM tiles, plausible broad
community positions, approximate markers and the correct coverage counts.
Chrome CLI captures the direct URL before asynchronous tile loading; final
screenshots used a passive transparent iframe harness with an 8-second pending
image to delay capture of the real app. No UI content was mocked, no virtual
time flag was used. Marker click/popup interaction has NOT been exercised, so
this is tile/position visual evidence, not full interaction acceptance.

Private artifacts: `.qa/geocode_review.csv`, `.qa/geocode_cache.json` and
`before-geocodes-20261109_081610.dump` in the QA checkout. Screenshots and full
manual-pin CSV/report are available to the operator under `/workspace/ohqa`.
