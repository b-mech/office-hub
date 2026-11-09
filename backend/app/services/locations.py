"""Manual location edits share the established tenant/actor authorization path."""
from datetime import datetime, timezone
from decimal import Decimal
from fastapi import HTTPException
from app.core.tenancy import require_rentals
from app.models.core import UserRole
from app.schemas.locations import LocationOut, LocationPatch

LOCATION_FIELDS = ("latitude", "longitude", "geocode_precision", "geocode_source", "geocoded_at")


def require_rental_editor(ctx):
    require_rentals(ctx)
    if ctx.is_readonly or not (ctx.is_superadmin or ctx.user.role == UserRole.ADMIN or (ctx.user.permissions or {}).get("rentals") == "editor"):
        raise HTTPException(403, "Rental editor access required")


def apply_location(row, patch: LocationPatch, actor_id):
    if patch.action == "reset":
        if row.geocode_snapshot is None:
            raise HTTPException(409, "No previous geocoded location to restore")
        snapshot = row.geocode_snapshot
        for name in LOCATION_FIELDS:
            value = snapshot.get(name)
            if name in {"latitude", "longitude"} and value is not None:
                value = Decimal(value)
            if name == "geocoded_at" and value:
                value = datetime.fromisoformat(value)
            setattr(row, name, value)
        row.location_set_by = None
        row.geocode_snapshot = None
    else:
        # Preserve the original geocode, not the previous manual adjustment.
        if row.geocode_snapshot is None and row.geocode_precision != "manual":
            row.geocode_snapshot = {name: str(getattr(row, name)) if getattr(row, name) is not None else None for name in LOCATION_FIELDS}
        if patch.action == "clear":
            row.latitude = row.longitude = None
            row.geocode_precision = row.geocode_source = None
            row.geocoded_at = None
            row.location_set_by = None
        else:
            row.latitude, row.longitude = patch.latitude, patch.longitude
            row.geocode_precision = row.geocode_source = "manual"
            row.geocoded_at = datetime.now(timezone.utc)
            row.location_set_by = actor_id


def location_payload(row, ctx):
    warnings = []
    if row.latitude is not None and row.longitude is not None and not (49 <= float(row.latitude) <= 60 and -102 <= float(row.longitude) <= -88.8):
        warnings.append("Pin is outside the usual Manitoba area. Check the coordinates.")
    return LocationOut(**{name: getattr(row, name) for name in LOCATION_FIELDS}, location_set_by=row.location_set_by,
                       can_reset_location=row.geocode_snapshot is not None, warnings=warnings, actor_is_fallback=ctx.is_fallback)
