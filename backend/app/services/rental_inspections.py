from __future__ import annotations
import asyncio
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.models.rentals import RentalInspection, RentalInspectionPhoto, RentalInspectionReportItem, RentalProperty, RentalUnit
from app.schemas.rental_inspections import InspectionCreate, InspectionPatch
from app.services.box import delete_file, get_or_create_subfolder, upload_file

async def create(db:AsyncSession,data:InspectionCreate)->RentalInspection:
    if not await db.get(RentalUnit,data.unit_id): raise ValueError("Rental unit not found")
    if data.inspection_type not in {"exterior","interior"}: raise ValueError("Inspection type must be exterior or interior")
    item=RentalInspection(**data.model_dump(),status="draft"); db.add(item); await db.commit(); await db.refresh(item); return item
async def patch(db:AsyncSession,item:RentalInspection,data:InspectionPatch)->RentalInspection:
    if data.inspection_type is not None and data.inspection_type not in {"exterior","interior"}: raise ValueError("Inspection type must be exterior or interior")
    for key,value in data.model_dump(exclude_unset=True).items(): setattr(item,key,value)
    await db.commit(); await db.refresh(item); return item
async def submit(db:AsyncSession,item:RentalInspection)->RentalInspection:
    if item.front_yard_score is None and not (item.front_yard_notes or "").strip(): raise ValueError("Front yard needs a score or explanatory note")
    if item.back_yard_score is None and not (item.back_yard_notes or "").strip(): raise ValueError("Back yard needs a score or explanatory note")
    item.status="submitted"; await db.commit(); await db.refresh(item); return item
async def upload_photos(db:AsyncSession,item:RentalInspection,files:list[tuple[str,bytes]],captions:list[str])->list[RentalInspectionPhoto]:
    unit=await db.get(RentalUnit,item.unit_id); prop=await db.get(RentalProperty,unit.property_id) if unit else None
    if not unit or not prop: raise ValueError("Inspection unit/property not found")
    parts=["PRIVI Inspections",prop.group_name or "Ungrouped",prop.street_address,unit.unit_label or "main",item.inspection_date.isoformat()]
    folder=settings.box_rental_properties_folder_id
    if not folder:
        raise RuntimeError("BOX_RENTAL_PROPERTIES_FOLDER_ID is not configured")
    for part in parts:
        folder=await asyncio.to_thread(get_or_create_subfolder,folder,part,raise_errors=True)
        if not folder: raise RuntimeError(f"Could not create Box folder: {part}")
    created=[]
    for index,(filename,content) in enumerate(files):
        file_id,url=await asyncio.to_thread(upload_file,folder,Path(filename).name,content,"image/jpeg",raise_errors=True)
        if not file_id: raise RuntimeError(f"Box upload failed for {filename}")
        photo=RentalInspectionPhoto(inspection_id=item.id,box_file_id=file_id,box_folder_path="/".join(parts),caption=captions[index] if index<len(captions) else None)
        db.add(photo); created.append(photo)
    await db.commit()
    for photo in created: await db.refresh(photo)
    return created
async def remove_photo(db:AsyncSession,photo:RentalInspectionPhoto)->None:
    if photo.box_file_id and not await asyncio.to_thread(delete_file,photo.box_file_id): raise RuntimeError("Could not delete photo from Box")
    await db.delete(photo); await db.commit()

async def delete(db:AsyncSession,item:RentalInspection)->None:
    linked=await db.scalar(select(RentalInspectionReportItem.id).where(RentalInspectionReportItem.inspection_id==item.id).limit(1))
    if linked is not None:
        raise ValueError("This inspection is included in an inspection report. Delete that report first.")
    photos=list((await db.scalars(select(RentalInspectionPhoto).where(RentalInspectionPhoto.inspection_id==item.id))).all())
    for photo in photos:
        if photo.box_file_id and not await asyncio.to_thread(delete_file,photo.box_file_id):
            raise RuntimeError("Could not delete an inspection photo from Box. The inspection was not deleted.")
    for photo in photos: await db.delete(photo)
    await db.delete(item); await db.commit()
