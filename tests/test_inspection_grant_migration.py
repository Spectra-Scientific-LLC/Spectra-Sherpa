"""The inspection schema grants nothing on upgrade and retains credential history."""

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from spectra_sherpa.app.models.project import Project
from spectra_sherpa.app.models.user import User
from tests.test_init_db_bootstrap import _run_downgrade, _run_upgrade


def test_upgrade_and_empty_downgrade(tmp_path):
    database = tmp_path / "inspection.db"
    url = f"sqlite+aiosqlite:///{database}"
    _run_upgrade(url, "r7s9t1u3v105")
    engine = sa.create_engine(f"sqlite:///{database}")
    try:
        assert not sa.inspect(engine).has_table("inspection_grant")
        _run_upgrade(url, "s8t0u2v4w216")
        assert sa.inspect(engine).has_table("inspection_grant")
        with engine.connect() as conn:
            assert conn.scalar(sa.text("SELECT COUNT(*) FROM inspection_grant")) == 0
        assert {index["name"] for index in sa.inspect(engine).get_indexes("inspection_grant")} == {
            "ix_inspection_grant_user_id",
            "ix_inspection_grant_project_id",
        }
        _run_downgrade(url, "r7s9t1u3v105")
        assert not sa.inspect(engine).has_table("inspection_grant")
    finally:
        engine.dispose()


def test_populated_downgrade_refuses_to_erase_revocation_history(tmp_path):
    from datetime import datetime, timedelta, timezone

    database = tmp_path / "retained.db"
    url = f"sqlite+aiosqlite:///{database}"
    _run_upgrade(url, "s8t0u2v4w216")
    engine = sa.create_engine(f"sqlite:///{database}")
    try:
        with Session(engine) as session:
            user = User(username="owner")
            session.add(user)
            session.flush()
            project = Project(user_id=user.id, name="Retained")
            session.add(project)
            session.flush()
            now = datetime.now(timezone.utc)
            session.execute(
                sa.insert(sa.Table("inspection_grant", sa.MetaData(), autoload_with=engine)).values(
                    id="registered-client",
                    user_id=user.id,
                    project_id=project.id,
                    client_label="Client",
                    token_digest="0" * 64,
                    disclosures=["metadata"],
                    created_at=now,
                    expires_at=now + timedelta(days=1),
                    revoked_at=now,
                )
            )
            session.commit()
        with pytest.raises(RuntimeError, match="reconciled"):
            _run_downgrade(url, "r7s9t1u3v105")
        with engine.connect() as conn:
            assert conn.scalar(sa.text("SELECT COUNT(*) FROM inspection_grant WHERE revoked_at IS NOT NULL")) == 1
    finally:
        engine.dispose()


def test_call_history_upgrade_and_populated_downgrade(tmp_path):
    from datetime import datetime, timedelta, timezone

    from spectra_sherpa.app.models.inspection_grant import InspectionCall

    database = tmp_path / "calls.db"
    url = f"sqlite+aiosqlite:///{database}"
    _run_upgrade(url, "s8t0u2v4w216")
    engine = sa.create_engine(f"sqlite:///{database}")
    try:
        _run_upgrade(url, "t9u1v3w5x327")
        assert sa.inspect(engine).has_table("inspection_call")
        _run_downgrade(url, "s8t0u2v4w216")
        assert not sa.inspect(engine).has_table("inspection_call")
        _run_upgrade(url, "t9u1v3w5x327")
        with Session(engine) as session:
            user = User(username="call-owner")
            session.add(user)
            session.flush()
            project = Project(user_id=user.id, name="Call history")
            session.add(project)
            session.flush()
            now = datetime.now(timezone.utc)
            session.execute(
                sa.insert(sa.Table("inspection_grant", sa.MetaData(), autoload_with=engine)).values(
                    id="call-client",
                    user_id=user.id,
                    project_id=project.id,
                    client_label="Client",
                    token_digest="1" * 64,
                    disclosures=["metadata"],
                    created_at=now,
                    expires_at=now + timedelta(days=1),
                )
            )
            session.flush()
            session.add(
                InspectionCall(
                    client_id="call-client",
                    project_id=project.id,
                    operation="list_node_types",
                    outcome="success",
                    response_bytes=20,
                    created_at=now,
                )
            )
            session.commit()
        with pytest.raises(RuntimeError, match="reconciliation"):
            _run_downgrade(url, "s8t0u2v4w216")
        with engine.connect() as conn:
            assert conn.scalar(sa.text("SELECT COUNT(*) FROM inspection_call")) == 1
    finally:
        engine.dispose()


def test_summary_consent_upgrade_does_not_expand_existing_grants(tmp_path):
    from datetime import datetime, timedelta, timezone

    database = tmp_path / "consent.db"
    url = f"sqlite+aiosqlite:///{database}"
    _run_upgrade(url, "t9u1v3w5x327")
    engine = sa.create_engine(f"sqlite:///{database}")
    try:
        with Session(engine) as session:
            user = User(username="catalog-owner")
            session.add(user)
            session.flush()
            project = Project(user_id=user.id, name="Original consent")
            session.add(project)
            session.flush()
            now = datetime.now(timezone.utc)
            table = sa.Table("inspection_grant", sa.MetaData(), autoload_with=engine)
            session.execute(
                sa.insert(table).values(
                    id="legacy-catalog",
                    user_id=user.id,
                    project_id=project.id,
                    client_label="Catalog only",
                    token_digest="a" * 64,
                    disclosures=["metadata"],
                    created_at=now,
                    expires_at=now + timedelta(days=1),
                    revoked_at=now,
                )
            )
            session.commit()
        _run_upgrade(url, "u0v2w4x6y438")
        with engine.connect() as conn:
            row = conn.execute(
                sa.text("SELECT project_summaries, token_digest, revoked_at FROM inspection_grant")
            ).one()
            assert row.project_summaries == 0
            assert row.token_digest == "a" * 64 and row.revoked_at is not None
        with pytest.raises(RuntimeError, match="consent history"):
            _run_downgrade(url, "t9u1v3w5x327")
        with engine.begin() as conn:
            conn.execute(sa.text("DELETE FROM inspection_grant"))
        _run_downgrade(url, "t9u1v3w5x327")
        assert "project_summaries" not in {c["name"] for c in sa.inspect(engine).get_columns("inspection_grant")}
    finally:
        engine.dispose()
