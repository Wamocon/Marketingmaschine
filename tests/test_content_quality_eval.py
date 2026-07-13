from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from marketing_machine.content_quality import (
    DIMENSION_WEIGHTS,
    MAX_REFINEMENT_ATTEMPTS,
    build_refinement_request,
    evaluate_content_payload,
    evaluate_content_quality,
    failed_check_codes,
    normalize_content_candidate,
)


ROOT = Path(__file__).resolve().parents[1]
GOLDEN_PATH = ROOT / "tests" / "fixtures" / "content_quality" / "golden_pass_k1_k5.json"
CLI_PATH = ROOT / "scripts" / "evaluate_content_quality.py"


def _golden_briefs() -> list[dict[str, Any]]:
    payload = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    return [copy.deepcopy(item["brief"]) for item in payload["items"]]


def _report(candidate: dict[str, Any]) -> dict[str, Any]:
    return evaluate_content_quality(candidate, repo_root=ROOT)


def test_golden_ai_outputs_for_all_five_campaigns_are_release_ready() -> None:
    report = evaluate_content_payload({"items": _golden_briefs()}, repo_root=ROOT)

    assert report["release_ready"] is True
    assert report["summary"] == {"total": 5, "passed": 5, "failed": 0}
    assert sum(DIMENSION_WEIGHTS.values()) == 100.0
    assert [item["campaign_id"] for item in report["results"]] == [
        "k1",
        "k2",
        "k3",
        "k4",
        "k5",
    ]
    for item in report["results"]:
        assert item["overall_score"] == 100.0
        assert item["hard_blockers"] == []
        assert item["critique"] == []
        assert item["refinement"]["external_ai_called"] is False
        assert sum(
            float(dimension["weight"])
            for dimension in item["dimensions"].values()
        ) == 100.0


def test_fallback_and_missing_ai_provenance_are_hard_failures() -> None:
    candidate = _golden_briefs()[1]
    candidate["generation"].update(
        {
            "status": "deterministic_fallback",
            "provider": "deterministic_rules",
            "model": "wamocon-safe-copy-v1",
            "fallback_used": True,
            "fallback_reason": "generation_failed",
            "error": "generation_failed",
            "structured_output_mode": "deterministic",
        }
    )

    report = _report(candidate)
    failures = failed_check_codes(report)

    assert report["release_ready"] is False
    assert "ai_provenance.ai_generated_status" in failures
    assert "ai_provenance.no_fallback" in failures
    assert "ai_provenance.provider_and_model" in failures
    assert "ai_provenance.no_generation_error" in failures
    assert report["refinement"]["required"] is True


def test_campaign_audience_offer_and_cross_campaign_mix_fail_closed() -> None:
    candidate = _golden_briefs()[0]
    candidate["persona"] = "Bewerber und B2B-Entscheider"
    candidate["cta"] = "Team kennenlernen"
    candidate["public_copy"] += "\n\nSokrates Private AI"

    failures = failed_check_codes(_report(candidate))

    assert "campaign_audience_offer_fit.canonical_persona" in failures
    assert "campaign_audience_offer_fit.canonical_offer" in failures
    assert "campaign_audience_offer_fit.no_cross_campaign_mix" in failures


def test_raw_technical_terms_and_incomplete_reel_fail() -> None:
    candidate = _golden_briefs()[2]
    candidate["reel_output"]["idea"] += " API JSON Payload"
    candidate["reel_output"]["script"] = candidate["reel_output"]["script"][:1]
    candidate["reel_output"]["shot_list"] = []

    failures = failed_check_codes(_report(candidate))

    assert "german_business_clarity.no_raw_technical_terms" in failures
    assert "format_completeness.reel_script" in failures
    assert "format_completeness.shot_list" in failures


def test_invented_citation_and_unsupported_number_fail_grounding() -> None:
    candidate = _golden_briefs()[0]
    candidate["citations"][0]["url"] = "https://invented-source.com/unsupported-claim"
    candidate["public_copy"] += "\n\n97 Prozent bessere Ergebnisse."
    candidate["channel_copy"]["body"] += " 97 Prozent bessere Ergebnisse."

    failures = failed_check_codes(_report(candidate))

    assert "source_grounding.citation_allowlist" in failures
    assert "source_grounding.no_unsupported_quantities" in failures


def test_k4_requires_operational_consent_and_real_asset_wording() -> None:
    candidate = _golden_briefs()[3]
    candidate["risk_flags"] = []
    candidate["reel_output"]["shot_list"] = [
        "Einstieg mit Team-Szene",
        "Schnitt auf Arbeitsalltag",
        "Endkarte",
    ]
    candidate["reel_output"]["script"] = [
        candidate["reel_output"]["caption"],
        "Ein Einblick für Bewerber und B2B-Entscheider.",
        "Team kennenlernen",
    ]
    candidate["reel_output"]["on_screen_text"] = ["Team", "Team kennenlernen"]
    candidate["reel_output"]["editing_notes"] = "Ruhig schneiden und die Endkarte zeigen."

    failures = failed_check_codes(_report(candidate))

    assert "campaign_audience_offer_fit.canonical_risk_flags" in failures
    assert "k4_people_assets.people_consent_risk_flag" in failures
    assert "k4_people_assets.consent_wording" in failures
    assert "k4_people_assets.real_asset_wording" in failures
    assert "k4_people_assets.conditional_usage" in failures


def test_governance_and_internal_material_fail_closed() -> None:
    candidate = _golden_briefs()[1]
    unsafe = " API_KEY=secret"
    candidate["public_copy"] += unsafe
    candidate["channel_copy"]["body"] += unsafe

    failures = failed_check_codes(_report(candidate))

    assert "german_business_clarity.no_raw_technical_terms" in failures
    assert "safety_policy.governance_policy" in failures
    assert "safety_policy.no_internal_material" in failures


def test_bounded_refinement_request_contains_only_structured_critique() -> None:
    candidate = _golden_briefs()[1]
    candidate["generation"]["fallback_used"] = True
    failed_report = _report(candidate)

    first = build_refinement_request(failed_report, attempt=0)
    second = build_refinement_request(failed_report, attempt=1)

    assert first["attempt"] == 1
    assert first["remaining_after_attempt"] == 1
    assert second["attempt"] == MAX_REFINEMENT_ATTEMPTS
    assert second["remaining_after_attempt"] == 0
    assert first["external_ai_called"] is False
    assert first["failures"]
    with pytest.raises(ValueError, match="refinement attempt"):
        build_refinement_request(failed_report, attempt=2)


def test_runtime_state_and_captured_generator_wrappers_normalize() -> None:
    brief = _golden_briefs()[2]
    generated = {
        "public_copy": brief.pop("public_copy"),
        "channel_copy": brief.pop("channel_copy"),
        "reel": brief.pop("reel_output"),
        "citations": brief.pop("citations"),
        "provenance": brief.pop("generation"),
    }
    captured = {"brief": brief, "generated": generated}

    normalized = normalize_content_candidate(captured)

    assert normalized["reel_output"] == generated["reel"]
    assert normalized["generation"] == generated["provenance"]
    assert _report(normalized)["release_ready"] is True


def test_cli_exit_codes_for_pass_quality_failure_and_invalid_input(tmp_path: Path) -> None:
    passed = subprocess.run(
        [sys.executable, str(CLI_PATH), str(GOLDEN_PATH)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert passed.returncode == 0
    assert json.loads(passed.stdout)["summary"]["passed"] == 5

    failed_candidate = _golden_briefs()[0]
    failed_candidate["generation"]["fallback_used"] = True
    failed_path = tmp_path / "failed.json"
    failed_path.write_text(json.dumps(failed_candidate, ensure_ascii=False), encoding="utf-8")
    failed = subprocess.run(
        [
            sys.executable,
            str(CLI_PATH),
            str(failed_path),
            "--refinement-attempt",
            "0",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    failed_payload = json.loads(failed.stdout)
    assert failed.returncode == 1
    assert failed_payload["release_ready"] is False
    assert failed_payload["results"][0]["refinement_request"]["attempt"] == 1

    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text("{not-json", encoding="utf-8")
    invalid = subprocess.run(
        [sys.executable, str(CLI_PATH), str(invalid_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert invalid.returncode == 2
    assert json.loads(invalid.stdout)["error"]["code"] == "invalid_input"
