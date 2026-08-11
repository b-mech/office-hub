from __future__ import annotations

from collections.abc import Awaitable
from typing import TypeVar
from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.program_allocations import AllocationCreate
from app.schemas.program_allocations import AllocationRequestCreate
from app.schemas.program_allocations import AllocationRequestOut
from app.schemas.program_allocations import AllocationRequestUpdate
from app.schemas.program_allocations import AllocationUpdate
from app.schemas.program_allocations import FitEvaluationOut
from app.schemas.program_allocations import FitEvaluationRequest
from app.schemas.program_allocations import ProgramCapacityOut
from app.schemas.program_allocations import ProgramCreate
from app.schemas.program_allocations import ProgramDetailOut
from app.schemas.program_allocations import ProgramUpdate
from app.schemas.program_allocations import TierCreate
from app.schemas.program_allocations import TierUpdate
from app.services import program_allocations


router = APIRouter(prefix="/api/v1/financing/programs", tags=["financing-programs"])
T = TypeVar("T")


@router.get("", response_model=list[ProgramCapacityOut])
@router.get("/", response_model=list[ProgramCapacityOut], include_in_schema=False)
async def list_programs(db: AsyncSession = Depends(get_db)) -> list[ProgramCapacityOut]:
    return await program_allocations.list_programs(db)


@router.post("", response_model=ProgramDetailOut, status_code=201)
@router.post("/", response_model=ProgramDetailOut, status_code=201, include_in_schema=False)
async def create_program(data: ProgramCreate, db: AsyncSession = Depends(get_db)) -> ProgramDetailOut:
    return await _run(db, program_allocations.create_program(db, data))


@router.post("/evaluate", response_model=FitEvaluationOut)
async def evaluate_property(
    data: FitEvaluationRequest, db: AsyncSession = Depends(get_db)
) -> FitEvaluationOut:
    return await _run(db, program_allocations.evaluate_property_fit(db, data))


@router.post("/allocation-requests", response_model=AllocationRequestOut, status_code=201)
async def create_request(
    data: AllocationRequestCreate, db: AsyncSession = Depends(get_db)
) -> AllocationRequestOut:
    return await _run(db, program_allocations.create_allocation_request(db, data))


@router.patch("/allocation-requests/{request_id}", response_model=AllocationRequestOut)
async def update_request(
    request_id: UUID,
    data: AllocationRequestUpdate,
    db: AsyncSession = Depends(get_db),
) -> AllocationRequestOut:
    return await _run(db, program_allocations.update_allocation_request(db, request_id, data))


@router.patch("/allocations/{allocation_id}", response_model=ProgramDetailOut)
async def update_allocation(
    allocation_id: UUID,
    data: AllocationUpdate,
    db: AsyncSession = Depends(get_db),
) -> ProgramDetailOut:
    return await _run(db, program_allocations.update_allocation(db, allocation_id, data))


@router.post("/allocations/{allocation_id}/tiers", response_model=ProgramDetailOut, status_code=201)
async def create_tier(
    allocation_id: UUID,
    data: TierCreate,
    db: AsyncSession = Depends(get_db),
) -> ProgramDetailOut:
    return await _run(db, program_allocations.create_tier(db, allocation_id, data))


@router.patch("/tiers/{tier_id}", response_model=ProgramDetailOut)
async def update_tier(
    tier_id: UUID,
    data: TierUpdate,
    db: AsyncSession = Depends(get_db),
) -> ProgramDetailOut:
    return await _run(db, program_allocations.update_tier(db, tier_id, data))


@router.get("/{program_id}", response_model=ProgramDetailOut)
async def program_detail(program_id: UUID, db: AsyncSession = Depends(get_db)) -> ProgramDetailOut:
    return await _run(db, program_allocations.get_program_detail(db, program_id))


@router.patch("/{program_id}", response_model=ProgramDetailOut)
async def update_program(
    program_id: UUID,
    data: ProgramUpdate,
    db: AsyncSession = Depends(get_db),
) -> ProgramDetailOut:
    return await _run(db, program_allocations.update_program(db, program_id, data))


@router.post("/{program_id}/allocations", response_model=ProgramDetailOut, status_code=201)
async def create_allocation(
    program_id: UUID,
    data: AllocationCreate,
    db: AsyncSession = Depends(get_db),
) -> ProgramDetailOut:
    return await _run(db, program_allocations.create_allocation(db, program_id, data))


@router.get("/{program_id}/capacity", response_model=ProgramCapacityOut)
async def program_capacity(
    program_id: UUID, db: AsyncSession = Depends(get_db)
) -> ProgramCapacityOut:
    return await _run(db, program_allocations.get_program_capacity(db, program_id))


async def _run(db: AsyncSession, operation: Awaitable[T]) -> T:
    try:
        return await operation
    except (
        program_allocations.ProgramNotFoundError,
        program_allocations.AllocationNotFoundError,
        program_allocations.AllocationRequestNotFoundError,
    ) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except program_allocations.ReleaseNotAllowedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Program configuration conflicts with an existing record.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
