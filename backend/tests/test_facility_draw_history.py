"""HTTP contracts with an isolated transaction store: no real DB/integrations."""
from copy import deepcopy
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.core.config import settings
from app.core.database import get_db
from app.core.tenancy import TenantContext, get_tenant
from app.models.core import UserRole, UserOrgRole, OrgProjectScope
from app.routers.financing import router
from app.services import financing


class Result:
    def __init__(self, rows=(), scalar=None): self.rows=list(rows); self.value=scalar
    def mappings(self): return self
    def one_or_none(self): return self.rows[0] if self.rows else None
    def all(self): return self.rows
    def scalar_one_or_none(self): return self.value


class Store:
    def __init__(self, lender="SCU"):
        self.facility={"id":uuid4(),"lender_type":lender,"lender":lender,"already_drawn":Decimal("150000.00")}
        self.rows=[];self.before=None;self.sql=[];self.commits=0;self.rollbacks=0;self.fail_insert_at=None;self.inserts=0;self.race_on_insert=False
    async def execute(self, stmt, params=None):
        sql=str(stmt).strip();p=params or {};self.sql.append(sql)
        if self.before is None:self.before=deepcopy(self.rows)
        if "FROM core.lender_facilities" in sql:
            return Result([self.facility] if p["facility_id"]==self.facility["id"] else [])
        if sql.startswith("SELECT id FROM core.facility_transactions"):
            matches=[r for r in self.rows if r["facility_id"]==p["facility_id"] and r["txn_date"]==p["txn_date"] and r["amount"]==p["amount"] and (r["reference"] or "")==p["reference"]]
            return Result(scalar=matches[0]["id"] if matches else None)
        if sql.startswith("INSERT INTO core.facility_transactions"):
            self.inserts+=1
            if self.fail_insert_at==self.inserts:raise RuntimeError("simulated store failure")
            assert "ON CONFLICT ON CONSTRAINT uq_facility_transactions_identity DO NOTHING" in sql
            row=dict(p,created_at=datetime(2026,11,9,tzinfo=timezone.utc)+timedelta(microseconds=len(self.rows)),statement_id=None,funds_entry_id=None,funds_notice_id=None)
            self.rows.append(row);return Result(scalar=None if self.race_on_insert else row["id"])
        if sql.startswith("SELECT id, source"):
            return Result([r for r in self.rows if r["id"]==p["txn_id"] and r["facility_id"]==p["facility_id"]])
        if sql.startswith("DELETE FROM core.facility_transactions"):
            self.rows=[r for r in self.rows if not (r["id"]==p["txn_id"] and r["facility_id"]==p["facility_id"])];return Result()
        if "ORDER BY txn_date, created_at, id" in sql:
            return Result(sorted([r for r in self.rows if r["facility_id"]==p["facility_id"] and r["txn_type"] in {"draw","repayment"}],key=lambda r:(r["txn_date"],r["created_at"],str(r["id"]))))
        raise AssertionError(sql)
    async def commit(self):self.commits+=1;self.before=None
    async def rollback(self):self.rollbacks+=1;self.rows=self.before if self.before is not None else self.rows;self.before=None


def ctx(*,org=None,readonly=False):
    return TenantContext(user=SimpleNamespace(id=uuid4(),role=UserRole.READONLY if readonly else UserRole.ADMIN),org=SimpleNamespace(id=org or settings.default_org_id,land_enabled=True,member_project_scope=OrgProjectScope.ORG),membership_role=UserOrgRole.TENANT_ADMIN,is_superadmin=False,is_fallback=True,explicit_org=False)


def client(store,tenant=None):
    app=FastAPI();app.include_router(router);app.dependency_overrides[get_db]=lambda:store;app.dependency_overrides[get_tenant]=lambda:tenant or ctx()
    return TestClient(app,raise_server_exceptions=False)


def path(store):return f"/api/v1/financing/facilities/{store.facility['id']}/draws"

def draw(**changes):return dict(txn_date="2026-10-15",amount="25000.25",reference="SCU-1",confirmed_by="Bank confirmation",percent_complete="35.50",notes="Confirmed progress advance",**changes) if not changes else {**draw(),**changes}


def test_create_list_metadata_totals_and_bank_balance_unchanged():
    db=Store();c=client(db);response=c.post(path(db),json=draw());assert response.status_code==200,response.text
    body=response.json();assert (body["created"],body["skipped"])==(1,0)
    assert body["results"][0]["status"]=="created"
    history=c.get(path(db)).json();r=history["items"][0]
    assert r["source"]=="scu_confirmation" and r["confirmed_by"]=="Bank confirmation" and r["percent_complete"]=="35.50"
    assert r["notes"]=="Confirmed progress advance" and r["can_delete"]
    assert history["sum_of_draws"]=="25000.25" and history["already_drawn"]=="150000.00"
    assert history["difference_from_already_drawn"]=="124999.75" and r["running_total"]=="25000.25"
    assert db.facility["already_drawn"]==Decimal("150000.00") and not any("UPDATE core.lender_facilities" in sql for sql in db.sql)


def test_bulk_sorted_repayments_running_total_and_duplicate_skips():
    db=Store();c=client(db)
    payload=[draw(txn_date="2026-10-20"),draw(txn_date="2026-10-01",amount="10000.00",reference="first"),draw(txn_date="2026-10-21",amount="5000.00",reference="repay",txn_type="repayment"),draw(txn_date="2026-10-20")]
    r=c.post(path(db),json=payload);assert r.status_code==200,r.text;b=r.json()
    assert (b["created"],b["skipped"])==(3,1)
    h=b["history"];assert [i["txn_date"] for i in h["items"]]==["2026-10-01","2026-10-20","2026-10-21"]
    assert h["sum_of_draws"]=="35000.25" and h["sum_of_repayments"]=="5000.00" and h["net_draws"]=="30000.25"
    assert [i["running_total"] for i in h["items"]]==["10000.00","35000.25","30000.25"]
    assert c.post(path(db),json=payload).json()["skipped"]==4
    assert len(db.rows)==3


@pytest.mark.parametrize("reference",[None,"","   "])
def test_optional_reference_retries_are_idempotent(reference):
    db=Store();c=client(db);first=c.post(path(db),json=draw(reference=reference)).json()
    second=c.post(path(db),json=draw(reference=None,notes="Different metadata is not an upsert")).json()
    assert second["skipped"]==1 and second["results"][0]["txn_id"]==first["results"][0]["txn_id"]
    assert len(db.rows)==1 and db.rows[0]["reference"]=="" and db.rows[0]["notes"]=="Confirmed progress advance"


def test_legacy_null_reference_is_recognized_and_not_duplicated():
    db=Store();c=client(db);c.post(path(db),json=draw(reference=None));db.rows[0]["reference"]=None
    assert c.post(path(db),json=draw(reference=None)).json()["skipped"]==1


def test_delete_is_scoped_restores_empty_history_and_never_changes_bank():
    db=Store();c=client(db);txn=c.post(path(db),json=draw()).json()["results"][0]["txn_id"]
    assert c.delete(f"/api/v1/financing/facilities/{uuid4()}/draws/{txn}").status_code==404
    r=c.delete(path(db)+"/"+txn);assert r.status_code==200,r.text
    assert r.json()["deleted"] and r.json()["history"]["items"]==[]
    assert r.json()["history"]["sum_of_draws"]=="0.00" and db.facility["already_drawn"]==Decimal("150000.00")
    assert c.delete(path(db)+"/"+txn).status_code==404


@pytest.mark.parametrize("source,link",[("lawyer_notice",None),("pro_reconciliation",None),("manual","statement_id"),("scu_confirmation","funds_entry_id"),("manual","funds_notice_id")])
def test_delete_protects_integrated_transactions(source,link):
    db=Store();c=client(db);txn=c.post(path(db),json=draw()).json()["results"][0]["txn_id"]
    db.rows[0]["source"]=source
    if link:db.rows[0][link]=uuid4()
    assert c.get(path(db)).json()["items"][0]["can_delete"] is False
    assert c.delete(path(db)+"/"+txn).status_code==409 and len(db.rows)==1


@pytest.mark.parametrize("lender",["STRIDE","RSU","CLIENT","OTHER"])
def test_other_non_pro_lenders_allowed_with_manual_default_source(lender):
    db=Store(lender);r=client(db).post(path(db),json=draw());assert r.status_code==200,r.text
    assert r.json()["history"]["items"][0]["source"]=="manual"


@pytest.mark.parametrize("changes",[{"amount":"0"},{"amount":"-1"},{"amount":"1.001"},{"amount":"NaN"},{"amount":"1000000000000"},{"percent_complete":"100.01"},{"percent_complete":"-1"},{"txn_date":"wrong"},{"txn_type":"interest"},{"source":"lawyer_notice"},{"already_drawn":"0"}])
def test_invalid_payload_is_422_and_does_not_write(changes):
    db=Store();r=client(db).post(path(db),json=draw(**changes));assert r.status_code==422,r.text
    assert db.rows==[] and db.commits==0


def test_bulk_validation_is_all_or_nothing_and_empty_rejected():
    db=Store();c=client(db)
    assert c.post(path(db),json=[]).status_code==422
    assert c.post(path(db),json=[draw(),draw(amount="-1")]).status_code==422
    assert db.rows==[] and db.commits==0


def test_store_failure_rolls_back_the_entire_bulk_batch():
    db=Store();db.fail_insert_at=2;r=client(db).post(path(db),json=[draw(),draw(reference="two")])
    assert r.status_code==500 and db.rows==[] and db.commits==0 and db.rollbacks==1


def test_confirmation_text_alias_and_explicit_manual_source():
    db=Store();payload=draw();payload.pop("notes");payload.update(confirmation_text="  Confirmed by email  ",source="manual")
    r=client(db).post(path(db),json=payload);assert r.status_code==200,r.text
    assert r.json()["history"]["items"][0]["notes"]=="Confirmed by email" and db.rows[0]["source"]=="manual"


def test_foreign_org_and_readonly_write_are_denied_before_database_access():
    db=Store();foreign=client(db,ctx(org=uuid4()))
    assert foreign.get(path(db)).status_code==403 and foreign.post(path(db),json=draw()).status_code==403
    assert foreign.delete(path(db)+"/"+str(uuid4())).status_code==403 and db.sql==[]
    readonly=client(db,ctx(readonly=True));assert readonly.get(path(db)).status_code==200
    assert readonly.post(path(db),json=draw()).status_code==403
    assert readonly.delete(path(db)+"/"+str(uuid4())).status_code==403


def test_pro_history_can_be_read_but_manual_writes_cannot_change_ledger(monkeypatch):
    db=Store("PRO");c=client(db)
    assert c.get(path(db)).status_code==200
    assert c.post(path(db),json=draw()).status_code==409 and db.rows==[]
    assert c.delete(path(db)+"/"+str(uuid4())).status_code==409
    expected=dict(facility_id=db.facility["id"],facility_key="PRO-1",property_name="Test",as_of=date(2026,11,9),balance_as_of=Decimal("120000.00"),events=[])
    ledger=AsyncMock(return_value=expected);monkeypatch.setattr(financing,"get_pro_ledger",ledger)
    response=c.get(path(db).replace("/draws","/ledger"));assert response.status_code==200,response.text
    assert response.json()["balance_as_of"]=="120000.00";ledger.assert_awaited_once_with(db,db.facility["id"])
    ledger.return_value=None;assert c.get(path(db).replace("/draws","/ledger")).status_code==404


def test_concurrent_unique_conflict_returns_skipped_existing_id():
    db=Store();db.race_on_insert=True;r=client(db).post(path(db),json=draw())
    assert r.status_code==200,r.text
    assert r.json()["created"]==0 and r.json()["skipped"]==1
    assert r.json()["results"][0]["txn_id"]==str(db.rows[0]["id"])


def test_missing_facility_is_404_and_unknown_bank_is_not_reported_as_zero():
    db=Store();c=client(db)
    assert c.get(f"/api/v1/financing/facilities/{uuid4()}/draws").status_code==404
    db.facility["already_drawn"]=None
    h=c.get(path(db)).json();assert h["already_drawn"] is None and h["difference_from_already_drawn"] is None


def test_identity_matches_existing_key_even_when_transaction_type_differs():
    db=Store();c=client(db);c.post(path(db),json=draw())
    r=c.post(path(db),json=draw(txn_type="repayment")).json()
    assert r["skipped"]==1 and r["history"]["items"][0]["txn_type"]=="draw"
