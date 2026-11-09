# Manual map pins and full-screen map workspace

Preview workflow: http://localhost:3058/lots/map (or /rentals/map) with the
3058/8058 SSH tunnel. Toggle Needs pin, select an item, then drag the orange
marker or click the map. Keyboard: focus the unsaved marker and use arrow keys.
Coordinates can also be entered in the tray. Save pin & next explicitly saves
and advances to the next item. Cancel discards the unsaved point.

All street and missing results need a manual pin; house/manual results do not.
Missing lots start near other pins in the same development, else a community
reference centre. These are ONLY editing start views: labelled UNPLACED and
UNSAVED, never automatically stored, and Save is disabled until moved/edited.
Manual points are solid and cannot be downgraded by overlapping street points.
Animated clusters expand/spiderfy coincident points; no stored coordinates are
jittered. Both maps fill the content viewport, with a floating toolbar and
collapsible details/queue tray (bottom sheet on mobile), not a page-length list.
Selection/fitting uses flyTo/flyToBounds; ResizeObserver invalidates map size.

## API
- PATCH /api/v1/lots/{lot_id}/location
- PATCH /api/rentals/properties/{property_id}/location

Body: {"latitude":49.98,"longitude":-97.08} (default action=set), or
{"action":"reset"}, or {"action":"clear"}. Set requires both finite worldwide
coordinates within latitude +/-90 and longitude +/-180. Outside the usual
Manitoba box produces a warning, not rejection; UI warns before Save too.

The first manual change snapshots the original geocoded fields. Further
manual adjustments preserve that snapshot. Reset restores original precision,
source, coordinates and geocoded_at; clear leaves no plotted point while
retaining the snapshot for reset. Manual saves set precision/source to manual,
record timestamp and location_set_by from the existing authenticated actor.
Clients cannot supply actor/precision/source fields. Lot writes require editor
access through development org and established lot/land authorization. Rentals
are default-CH-org only and require rental editor/admin access. Property map
reads use the same tenant path. Cookie-auth writes retain middleware CSRF checks.
AUTH_ENFORCED=false in preview means the established fallback actor is recorded;
this is not signed-in security acceptance against production.

Geocoder always skips manual points, including --force. Only the explicit
--include-manual flag with --force permits replacing them. A DB update predicate
also protects a pin manually saved while a geocoding batch is in flight.

## Deployment / migration
20261109_0060 follows 20261109_0059. Adds nullable location_set_by (FK core.users,
ON DELETE SET NULL) and geocode_snapshot JSONB on core.lots/rental_properties.
Preview only, after pg_dump backup. PR #3 has separate 0058: retain a reviewed
merge revision before joint deployment; do not renumber either history.

## QA
Backend endpoint tests cover validation, actor spoof rejection, cross-org 404,
readonly rejection, CH rental editor scope, warning-only out-of-area coordinates,
and set/adjust/clear/reset roundtrip. Helper tests cover unsaved starts, queue
advance, manual marker precedence and geocoder preservation. Full backend suite,
frontend unit tests, tsc, build and API URL guard must pass before handoff.
Visual stills can check viewport layout/tiles/controls, not animation smoothness
or real mouse dragging. Preview API smoke saves one temporary test location
through the frontend proxy and resets it to its exact prior location fields.

Reset regression: ORM JSON snapshots use none_as_null=True, and lot API flags
require a JSON object rather than merely a non-NULL SQL value. This prevents a
JSON null from advertising a reset option after the original geocode is restored.
The issue was discovered by the real preview proxy roundtrip, not just mocks.
