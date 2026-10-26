import pytest
from sqlalchemy import select

from spectra_sherpa.app.models.project import Project
from spectra_sherpa.app.models.time_series_portfolio import TimeSeriesPortfolioRecord
from spectra_sherpa.core.time_series_portfolio import TimeSeriesPortfolio
from tests.test_time_series_portfolio import partition


@pytest.mark.asyncio
async def test_named_portfolio_is_immutable_and_duplicate_names_refused(
    auth_client, test_session, test_user, monkeypatch
):
    project = Project(user_id=test_user.id, name="OES test")
    test_session.add(project)
    await test_session.commit()
    await test_session.refresh(project)
    project_id = project.id
    receipt = TimeSeriesPortfolio(project_id=project_id, partitions=(partition(),))

    async def build(*args, **kwargs):
        return receipt

    monkeypatch.setattr("spectra_sherpa.app.api.v1.routes.time_series_portfolios.build_portfolio", build)
    url = f"/api/v1/projects/{project_id}/time-series-portfolios"
    body = {
        "name": "Etch",
        "selections": [
            {"experiment_id": 1, "file_id": 2, "process_file_id": 3, "asset_id": "Wafer_01", "step_id": "production"}
        ],
    }
    saved = await auth_client.post(url, json=body)
    assert saved.status_code == 201, saved.text
    assert saved.json()["selection_sha256"] == receipt.sha256()
    assert (await auth_client.get(url)).json()[0]["name"] == "Etch"
    assert (await auth_client.put(url + "/" + str(saved.json()["id"]), json={"name": "Changed"})).status_code in (
        404,
        405,
    )
    duplicate = await auth_client.post(url, json=body | {"name": " etch "})
    assert duplicate.status_code == 409
    await test_session.refresh(test_user)
    records = (await test_session.scalars(select(TimeSeriesPortfolioRecord))).all()
    assert len(records) == 1 and records[0].selection == receipt.model_dump(mode="json")


@pytest.mark.asyncio
async def test_portfolio_cannot_be_saved_into_another_users_project(auth_client, test_session, test_user):
    from spectra_sherpa.app.models.user import User

    other = User(username="portfolio-other")
    test_session.add(other)
    await test_session.flush()
    project = Project(user_id=other.id, name="Private")
    test_session.add(project)
    await test_session.commit()
    await test_session.refresh(project)
    response = await auth_client.get(f"/api/v1/projects/{project.id}/time-series-portfolios")
    assert response.status_code in (403, 404)
