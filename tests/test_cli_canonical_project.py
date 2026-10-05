"""CLI coverage for the one current canonical project user journey."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from spectra_sherpa import cli
from spectra_sherpa.sdk import campaign_review, canonical_public_fixture, canonical_reproduction


class _Response:
    def __init__(self, payload: bytes, digest: str) -> None:
        self._payload = payload
        self.headers = {"X-Spectra-Campaign-Review-SHA256": digest}

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self._payload if size < 0 else self._payload[:size]


def test_campaign_review_download_verifies_server_digest_before_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"current-canonical-project"
    digest = hashlib.sha256(payload).hexdigest()
    seen: dict[str, object] = {}

    def fake_urlopen(request):
        seen["url"] = request.full_url
        seen["authorization"] = request.headers["Authorization"]
        return _Response(payload, digest)

    monkeypatch.setenv("CANONICAL_TOKEN", "secret-token")
    monkeypatch.setattr(cli, "urlopen", fake_urlopen)
    output = tmp_path / "campaign.sherpa"

    cli._campaign_review_download(
        "campaign-001",
        str(output),
        "https://managed.example/api/v1",
        "CANONICAL_TOKEN",
    )

    assert output.read_bytes() == payload
    assert seen == {
        "url": "https://managed.example/api/v1/harness/canonical-campaigns/campaign-001/campaign-review",
        "authorization": "Bearer secret-token",
    }


def test_campaign_review_download_rejects_unbound_or_overwriting_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"current-canonical-project"
    monkeypatch.setenv("TOKEN", "secret-token")
    monkeypatch.setattr(cli, "urlopen", lambda _request: _Response(payload, "0" * 64))
    output = tmp_path / "campaign.sherpa"

    with pytest.raises(SystemExit, match="digest is missing or invalid"):
        cli._campaign_review_download("campaign-001", str(output), "https://managed.example", "TOKEN")
    assert not output.exists()

    output.write_bytes(b"existing")
    with pytest.raises(SystemExit, match="already exists"):
        cli._campaign_review_download("campaign-001", str(output), "https://managed.example", "TOKEN")
    assert output.read_bytes() == b"existing"


def test_campaign_review_download_requires_authentication_before_network_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MISSING_TOKEN", raising=False)
    monkeypatch.setattr(
        cli,
        "urlopen",
        lambda _request: pytest.fail("an unauthenticated export must not reach the network"),
    )

    with pytest.raises(SystemExit, match="requires a bearer token in MISSING_TOKEN"):
        cli._campaign_review_download(
            "campaign/with/path-separator",
            str(tmp_path / "campaign.sherpa"),
            "https://managed.example",
            "MISSING_TOKEN",
        )


def test_campaign_review_cli_bootstraps_the_exact_local_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    from spectra_sherpa.app import types

    calls: list[bool] = []
    monkeypatch.setattr(types, "ensure_type_registry_loaded", lambda: calls.append(True))

    cli._ensure_campaign_review_runtime()

    assert calls == [True]


def test_canonical_project_reproduce_runs_the_current_oss_verifier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_path = tmp_path / "campaign.sherpa"
    project_path.write_bytes(b"project-bytes")
    fixture_path = tmp_path / "fixture.npz"
    fixture_path.write_bytes(b"fixture-bytes")
    anchors_path = tmp_path / "anchors.json"
    anchors_path.write_text('{"anchors":true}', encoding="utf-8")
    report_path = tmp_path / "report.json"
    package = object()
    review = SimpleNamespace(
        application=package,
        publisher_attestation=SimpleNamespace(as_dict=lambda: {"attestation": True}),
    )
    fixture = SimpleNamespace(capability=object(), split_plan=object())
    seen: dict[str, object] = {}

    monkeypatch.setattr(campaign_review, "load_review_package_bytes", lambda _value: b"review-bytes")
    monkeypatch.setattr(campaign_review.CampaignReviewPackage, "from_archive", lambda _value: review)
    monkeypatch.setattr(
        canonical_public_fixture,
        "load_canonical_public_fixture",
        lambda path, loaded, **kwargs: (
            seen.update({"fixture_path": path, "package": loaded, "binding": kwargs}) or fixture
        ),
    )

    def reproduce(value, **kwargs):
        seen.update({"project_bytes": value, "reproduction": kwargs})
        return SimpleNamespace(
            as_dict=lambda: {
                "integrity_verified": {"status": "passed"},
                "publisher_authenticated": {"status": "passed"},
                "validation_reproduced": {"status": "passed"},
                "application_reproduced": {"status": "passed"},
            }
        )

    monkeypatch.setattr(canonical_reproduction, "reproduce_canonical_project", reproduce)

    cli._canonical_project_reproduce(
        str(project_path),
        str(fixture_path),
        "public-fixture-001",
        "wavenumber",
        "cm-1",
        str(anchors_path),
        str(report_path),
    )

    assert json.loads(report_path.read_text(encoding="utf-8")) == {
        "application_reproduced": {"status": "passed"},
        "integrity_verified": {"status": "passed"},
        "publisher_authenticated": {"status": "passed"},
        "validation_reproduced": {"status": "passed"},
    }
    assert seen["project_bytes"] is package
    assert seen["binding"] == {
        "custody_id": "public-fixture-001",
        "spectral_axis_title": "wavenumber",
        "spectral_axis_units": "cm-1",
    }
    assert seen["reproduction"] == {
        "fixture": fixture.capability,
        "split_plan": fixture.split_plan,
        "publisher_attestation": {"attestation": True},
        "publisher_trust_anchors": {"anchors": True},
    }


def test_canonical_project_reproduce_accepts_exact_provider_reference_without_manual_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_path = tmp_path / "campaign.sherpa"
    project_path.write_bytes(b"project-bytes")
    provider_path = tmp_path / "provider-download.zip"
    provider_path.write_bytes(b"provider-bytes")
    package = object()
    review = SimpleNamespace(
        application=package,
        publisher_attestation=SimpleNamespace(as_dict=lambda: {"attestation": True}),
    )
    fixture = SimpleNamespace(capability=object(), split_plan=object())
    seen: dict[str, object] = {}

    monkeypatch.setattr(campaign_review, "load_review_package_bytes", lambda _value: b"review-bytes")
    monkeypatch.setattr(campaign_review.CampaignReviewPackage, "from_archive", lambda _value: review)
    monkeypatch.setattr(
        canonical_public_fixture,
        "load_registered_reference_fixture",
        lambda path, loaded, **kwargs: (
            seen.update({"fixture_path": path, "package": loaded, "binding": kwargs}) or fixture
        ),
    )
    monkeypatch.setattr(
        canonical_reproduction,
        "reproduce_canonical_project",
        lambda value, **kwargs: (
            seen.update({"project_bytes": value, "reproduction": kwargs})
            or SimpleNamespace(
                as_dict=lambda: {
                    "integrity_verified": {"status": "passed"},
                    "publisher_authenticated": {"status": "passed"},
                    "validation_reproduced": {"status": "passed"},
                    "application_reproduced": {"status": "passed"},
                }
            )
        ),
    )

    cli._canonical_project_reproduce(
        str(project_path),
        str(provider_path),
        None,
        None,
        None,
        None,
        None,
        "eigenvector.corn.m5.moisture",
    )

    assert seen["fixture_path"] == provider_path
    assert seen["binding"] == {"projection_id": "eigenvector.corn.m5.moisture"}
    assert seen["reproduction"] == {
        "fixture": fixture.capability,
        "split_plan": fixture.split_plan,
        "publisher_attestation": {"attestation": True},
        "publisher_trust_anchors": None,
    }


def test_canonical_project_reproduce_writes_diagnostics_then_exits_nonzero_when_not_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_path = tmp_path / "campaign.sherpa"
    project_path.write_bytes(b"project-bytes")
    fixture_path = tmp_path / "fixture.npz"
    fixture_path.write_bytes(b"fixture-bytes")
    report_path = tmp_path / "report.json"
    review = SimpleNamespace(
        application=object(),
        publisher_attestation=SimpleNamespace(as_dict=lambda: {"attestation": True}),
    )
    fixture = SimpleNamespace(capability=object(), split_plan=object())
    monkeypatch.setattr(campaign_review, "load_review_package_bytes", lambda _value: b"review-bytes")
    monkeypatch.setattr(campaign_review.CampaignReviewPackage, "from_archive", lambda _value: review)
    monkeypatch.setattr(canonical_public_fixture, "load_canonical_public_fixture", lambda *_args, **_kwargs: fixture)
    monkeypatch.setattr(
        canonical_reproduction,
        "reproduce_canonical_project",
        lambda *_args, **_kwargs: SimpleNamespace(
            as_dict=lambda: {
                "integrity_verified": {"status": "passed"},
                "publisher_authenticated": {"status": "passed"},
                "validation_reproduced": {"status": "not_run"},
                "application_reproduced": {"status": "not_run"},
            }
        ),
    )

    with pytest.raises(SystemExit, match="validation_reproduced, application_reproduced"):
        cli._canonical_project_reproduce(
            str(project_path),
            str(fixture_path),
            "public-fixture-001",
            "wavenumber",
            "cm-1",
            None,
            str(report_path),
        )

    assert json.loads(report_path.read_text(encoding="utf-8"))["validation_reproduced"] == {"status": "not_run"}


def test_cli_exposes_the_named_campaign_review_journey(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, object] = {}

    def export(campaign_id: str, output: str, api_url: str, token_env: str) -> None:
        captured.update(
            campaign_id=campaign_id,
            output=output,
            api_url=api_url,
            token_env=token_env,
        )

    monkeypatch.setattr(cli, "_campaign_review_download", export)
    cli.main(
        [
            "campaign-review",
            "download",
            "campaign-001",
            "campaign.sherpa",
            "--api-url",
            "https://managed.example",
        ]
    )

    assert captured == {
        "campaign_id": "campaign-001",
        "output": "campaign.sherpa",
        "api_url": "https://managed.example",
        "token_env": "SPECTRA_SHERPA_TOKEN",
    }

    with pytest.raises(SystemExit) as exc_info:
        cli.main(["harness", "verify", "handoff.json"])
    assert exc_info.value.code == 2
    assert "invalid choice: 'harness'" in capsys.readouterr().err


def test_cli_routes_registered_reference_reproduction_without_npz_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        cli,
        "_canonical_project_reproduce",
        lambda *args: captured.update(args=args),
    )

    cli.main(
        [
            "campaign-review",
            "reproduce",
            "corn-review.sherpa",
            "corn-provider.zip",
            "--registered-reference-projection",
            "public-corn-m5-moisture-v1",
            "--publisher-trust-anchors",
            "anchors.json",
            "--report",
            "corn-report.json",
        ]
    )

    assert captured["args"] == (
        "corn-review.sherpa",
        "corn-provider.zip",
        None,
        None,
        None,
        "anchors.json",
        "corn-report.json",
        "public-corn-m5-moisture-v1",
    )
