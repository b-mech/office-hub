from __future__ import annotations
from datetime import date, datetime
from pydantic import BaseModel, ConfigDict, Field

class InspectionCreate(BaseModel):
    unit_id:int
    inspection_type:str="exterior"
    inspection_date:date=Field(default_factory=date.today)
    inspector_name:str|None=None
class InspectionPatch(BaseModel):
    inspection_type:str|None=None; inspection_date:date|None=None; inspector_name:str|None=None
    front_yard_score:int|None=Field(None,ge=1,le=10); front_yard_notes:str|None=None
    back_yard_score:int|None=Field(None,ge=1,le=10); back_yard_notes:str|None=None
    building_condition:str|None=None; building_notes:str|None=None; occupancy_flag:str|None=None; general_notes:str|None=None
class PhotoOut(BaseModel):
    model_config=ConfigDict(from_attributes=True)
    id:int; inspection_id:int; box_file_id:str|None; box_folder_path:str|None; caption:str|None; uploaded_at:datetime
    preview_url:str|None=None
class InspectionOut(BaseModel):
    model_config=ConfigDict(from_attributes=True)
    id:int; unit_id:int; inspection_type:str; inspection_date:date; inspector_name:str|None
    front_yard_score:int|None; front_yard_notes:str|None; back_yard_score:int|None; back_yard_notes:str|None
    building_condition:str|None; building_notes:str|None; occupancy_flag:str|None; general_notes:str|None; status:str
    photos:list[PhotoOut]=Field(default_factory=list)

class ReportCreate(BaseModel):
    title:str=Field(min_length=1,max_length=200)
    inspection_ids:list[int]=Field(min_length=1)
    expires_in_days:int=Field(default=7,ge=1,le=30)

class ReportSend(BaseModel):
    recipient_email:str=Field(min_length=3,max_length=255)

class ReportNotePatch(BaseModel):
    notes:str=Field(max_length=5000)

class ReportCommentCreate(BaseModel):
    author_name:str=Field(min_length=1,max_length=100)
    body:str=Field(min_length=1,max_length=5000)
