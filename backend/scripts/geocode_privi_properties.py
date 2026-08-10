from __future__ import annotations
import argparse, asyncio
from decimal import Decimal
import httpx
from sqlalchemy import select
import app.modules.costbook.models  # Register models referenced by shared ORM relationships.
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.rentals import RentalProperty

async def main(force:bool)->None:
    if not settings.google_maps_backend_api_key: raise SystemExit("GOOGLE_MAPS_BACKEND_API_KEY is not configured")
    success=[]; flagged=[]; failed=[]
    async with AsyncSessionLocal() as db, httpx.AsyncClient(timeout=30) as client:
        properties=list((await db.scalars(select(RentalProperty).order_by(RentalProperty.street_address))).all())
        for prop in properties:
            if not force and prop.latitude is not None and prop.longitude is not None: continue
            address=f"{prop.street_address}, {prop.city or ''}, Manitoba, Canada"
            response=await client.get("https://maps.googleapis.com/maps/api/geocode/json",params={"address":address,"key":settings.google_maps_backend_api_key});response.raise_for_status();payload=response.json()
            if payload.get("status")!="OK" or not payload.get("results"):
                failed.append((prop.id,prop.street_address,payload.get("status")));continue
            result=payload["results"][0];location=result["geometry"]["location"];quality=result["geometry"].get("location_type","UNKNOWN")
            prop.latitude=Decimal(str(location["lat"]));prop.longitude=Decimal(str(location["lng"]));(success if quality=="ROOFTOP" else flagged).append((prop.id,prop.street_address,quality,result.get("formatted_address")))
        await db.commit()
    print(f"Geocoded successfully ({len(success)}):",success);print(f"Flagged for review ({len(flagged)}):",flagged);print(f"Failed ({len(failed)}):",failed)
if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--force",action="store_true");args=parser.parse_args();asyncio.run(main(args.force))
