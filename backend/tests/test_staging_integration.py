from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("copy_worker_history", ROOT / "ops/staging-integration/copy_worker_history.py")
copy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(copy)
NOW = datetime(2026, 11, 10, tzinfo=timezone.utc)


def test_merge_graph_and_branch_specific_full_rollback():
    cfg = Config()
    cfg.set_main_option("script_location", str(ROOT / "backend/alembic"))
    graph = ScriptDirectory.from_config(cfg)
    assert graph.get_heads() == ["20261110_0062"]
    assert graph.get_revision("20261110_0062").down_revision == ("20261102_0055", "20261009_0051")
    steps = graph._downgrade_revs("20261009_0051@20261001_0047", ("20261102_0055", "20261009_0051"))
    assert [step.revision.revision for step in steps] == ["20261009_0051", "20261005_0050", "20261002_0049", "20261002_0048"]


def test_configparser_preserves_percent_encoded_database_credentials():
    value = "postgresql+asyncpg://test:p%40ss%25word@localhost/officehub_trial_test"
    cfg = Config()
    cfg.set_main_option("sqlalchemy.url", value.replace("%", "%%"))
    assert cfg.get_main_option("sqlalchemy.url") == value
    assert 'settings.database_url.replace("%", "%%")' in (ROOT / "backend/alembic/env.py").read_text()


@pytest.mark.parametrize("target,expected,live", [
    ("officehub_staging", "officehub_staging", False),
    ("officehub_trial_other", "officehub_trial_test", False),
    ("other_trial_test", "other_trial_test", False),
    ("officehub_source", "officehub_source", True),
])
def test_copy_target_guards_reject_wrong_or_live_database(target, expected, live):
    with pytest.raises(ValueError):
        copy.guard_target("postgresql+asyncpg://x:y@localhost/officehub_source", f"postgresql+asyncpg://x:y@localhost/{target}", expected, live)


def test_copy_target_exact_trial_and_explicit_live_guards():
    source = "postgresql+asyncpg://x:y@localhost/officehub_source"
    copy.guard_target(source, "postgresql+asyncpg://x:y@localhost/officehub_trial_test", "officehub_trial_test")
    copy.guard_target(source, "postgresql+asyncpg://x:y@localhost/officehub_staging", "officehub_staging", True)


def test_natural_keys_map_identity_not_colliding_integer_primary_keys():
    assert copy.natural_key("rental_properties", {"id": 1, "company_id": 2, "street_address": " 1 Test Street "}) == copy.natural_key("rental_properties", {"id": 42, "company_id": 2, "street_address": "1 TEST STREET"})
    assert copy.natural_key("rental_properties", {"company_id": 1, "street_address": "1 Test Street"}) != copy.natural_key("rental_properties", {"company_id": 2, "street_address": "1 Test Street"})
    with pytest.raises(ValueError, match="Ambiguous"):
        copy.unique_index("rental_companies", [{"name": "TEST"}, {"name": "test"}])


@pytest.mark.parametrize("status", ["pending", "held"])
def test_pending_outbound_sms_is_cancelled_not_replayed(status):
    original = {"direction": "outbound", "status": status}
    row, changed = copy.quarantine("maint_sms_messages", original, NOW)
    assert changed and row["status"] == "cancelled" and row["cancelled_at"] == NOW
    assert row["error_code"] == "staging_history_import_no_replay"
    assert original["status"] == status


@pytest.mark.parametrize("row", [{"direction": "inbound", "status": "received"}, {"direction": "outbound", "status": "queued"}, {"direction": "outbound", "status": "failed"}])
def test_existing_sms_history_does_not_change(row):
    assert copy.quarantine("maint_sms_messages", row, NOW) == (row, False)


def test_pending_slack_is_terminal_and_delivered_history_is_preserved():
    row, changed = copy.quarantine("maint_slack_outbox", {"delivered_at": None, "failed_at": None, "claimed_at": NOW}, NOW)
    assert changed and row["failed_at"] == NOW and row["claimed_at"] is None
    original = {"delivered_at": NOW, "failed_at": None}
    assert copy.quarantine("maint_slack_outbox", original, NOW) == (original, False)


def test_imported_actor_is_disabled_and_has_no_live_contact_or_auth_binding():
    actor = copy.historical_actor(dict(id=uuid4(), email="actor@example.invalid", full_name="Test Actor", role="admin", is_active=True, google_subject="dummy", phone_e164="+12045551234", slack_user_id="dummy", permissions={"admin": True}), uuid4())
    assert not actor["is_active"] and actor["role"] == "readonly" and not actor["permissions"]
    assert not {"google_subject", "phone_e164", "slack_user_id"}.intersection(actor)


def load_operator(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "ops/staging-integration" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_candidate_envs_keep_lease_integrations_and_align_worker_db():
    env = load_operator("prepare_env")
    lease = dict(ENVIRONMENT="staging", DATABASE_URL="postgresql+asyncpg://x:y@localhost/officehub_lease_agreements_test", DOCUSIGN_INTEGRATION_KEY="dummy-lease", DEFAULT_ORG_ID="dummy-lease-org")
    worker = dict(ENVIRONMENT="staging", DATABASE_URL="postgresql+asyncpg://x:y@localhost/officehub_staging", STAGING_SMS_ALLOWLIST="+12045551234", SLACK_CHANNEL_ID="dummy-staging", RINGCENTRAL_FROM_NUMBER="+12045555678", DEFAULT_ORG_ID="dummy-worker-org")
    backend, aligned = env.combine(lease, worker)
    assert backend["DOCUSIGN_INTEGRATION_KEY"] == "dummy-lease"
    assert backend["DEFAULT_ORG_ID"] == "dummy-lease-org"
    assert aligned["DEFAULT_ORG_ID"] == "dummy-worker-org"
    assert backend["DATABASE_URL"] == aligned["DATABASE_URL"] == lease["DATABASE_URL"]
    assert backend["STAGING_SMS_ALLOWLIST"] == worker["STAGING_SMS_ALLOWLIST"]
    with pytest.raises(ValueError):
        env.combine(lease, dict(worker, STAGING_SMS_ALLOWLIST=""))
    with pytest.raises(ValueError):
        env.combine(dict(lease, ENVIRONMENT="production"), worker)


def test_candidate_env_roundtrip_is_private_and_never_overwrites(tmp_path):
    from dotenv import dotenv_values
    env = load_operator("prepare_env")
    path = tmp_path / "candidate.env"
    values = {"DUMMY": "quotes ' and slash \\ and newline\nnext", "URL": "postgresql+asyncpg://x:p%40ss@localhost/officehub_trial_test"}
    env.write_new(path, values)
    assert dict(dotenv_values(path)) == values
    assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        env.write_new(path, values)


def test_db_operator_refuses_production_and_unapproved_staging_writes():
    db = load_operator("db_ops")
    with pytest.raises(ValueError):
        db.validate("postgresql+asyncpg://x:y@localhost/officehub_production", "officehub_production", True, True)
    with pytest.raises(ValueError):
        db.validate("postgresql+asyncpg://x:y@localhost/officehub_lease_agreements_test", "officehub_lease_agreements_test", True)


def test_candidate_unit_overrides_use_only_staging_ports_and_preserve_beat_state():
    op = load_operator("make_overrides")
    frontend = op.contents("frontend", "/release", "/protected-env")
    assert "BACKEND_INTERNAL_URL=http://127.0.0.1:8001" in frontend
    assert "EnvironmentFile=/protected-env/frontend.env" in frontend  # cloned lease env, explicitly pinned staging SSR URL
    for name in ["backend", "worker", "beat"]:
        value = op.contents(name, "/release", "/protected-env")
        assert "WorkingDirectory=/release/backend" in value
        assert "EnvironmentFile=\nEnvironmentFile=/protected-env/" in value
        assert "ExecStart=\nExecStart=/release/.venv/" in value
    assert "%S/officehub-staging/celerybeat-schedule" in op.contents("beat", "/release", "/protected-env")
