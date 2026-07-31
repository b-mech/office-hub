from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.facility_assignments import FacilityAssignmentCreate
from app.schemas.financing import FacilityOut
from app.services import facility_assignments
from app.services import lenders


router = APIRouter(
    prefix="/api/v1/financing/properties",
    tags=["financing-facilities"],
)


@router.post("/{property_id}/facilities", response_model=FacilityOut, status_code=201)
async def assign_property_facility(
    property_id: UUID,
    data: FacilityAssignmentCreate,
    db: AsyncSession = Depends(get_db),
) -> FacilityOut:
    try:
        return await facility_assignments.assign_facility(db, property_id, data)
    except facility_assignments.PropertyNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except facility_assignments.LenderNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except facility_assignments.ActiveFacilityExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except lenders.DuplicateLenderNameError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except facility_assignments.InvalidFacilityAssignmentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
