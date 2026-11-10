"""Vendor administration; the partial unique index arbitrates concurrent saves."""
from datetime import datetime, timezone
from sqlalchemy import select
from app.models.maintenance import MaintDirection,MaintEvent,MaintEventChannel,MaintParty,MaintVendor,MaintVisibility,MaintWorkOrder
from app.services.maintenance.phones import normalize_phone

class DuplicateVendorPhone(ValueError): pass


def vendor_view(vendor):
    return {"id":vendor.id,"name":vendor.name,"phone_e164":vendor.phone_e164,
        "trades":vendor.trades,"insurance_expiry":vendor.insurance_expiry,"wcb_expiry":vendor.wcb_expiry,
        "notes":vendor.notes,"is_active":vendor.is_active}


async def save_vendor(db,values,*,vendor=None,actor_user_id=None):
    for required in {"name","phone_e164","trades","is_active"}:
        if required in values and values[required] is None: raise ValueError(f"{required} cannot be cleared")
    if "phone_e164" in values: values["phone_e164"]=normalize_phone(values["phone_e164"])
    phone=values.get("phone_e164",vendor.phone_e164 if vendor else None)
    active=values.get("is_active",vendor.is_active if vendor else True)
    if active:
        query=select(MaintVendor.id).where(MaintVendor.phone_e164==phone,MaintVendor.is_active.is_(True))
        if vendor is not None: query=query.where(MaintVendor.id!=vendor.id)
        if await db.scalar(query) is not None: raise DuplicateVendorPhone("An active vendor already uses this phone")
    deactivating=bool(vendor is not None and vendor.is_active and not active)
    if vendor is None: vendor=MaintVendor(**values);db.add(vendor)
    else:
        for key,value in values.items():setattr(vendor,key,value)
    if deactivating:
        # Reactivating a vendor must not revive old capability links.
        orders=list((await db.scalars(select(MaintWorkOrder).where(
            MaintWorkOrder.vendor_id==vendor.id,MaintWorkOrder.access_token_hash.is_not(None)).with_for_update())).all())
        for order in orders:
            order.access_token_hash=None;order.token_expires_at=datetime.now(timezone.utc)
            db.add(MaintEvent(ticket_id=order.ticket_id,work_order_id=order.id,event_type="vendor_link_revoked",
                channel=MaintEventChannel.WEB,visibility=MaintVisibility.INTERNAL,direction=MaintDirection.NONE,
                actor_party=MaintParty.STAFF,actor_user_id=actor_user_id,payload={"reason":"vendor_deactivated"}))
    await db.flush()
    return vendor
