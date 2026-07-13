import re
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from marketing_machine.ui import render_marketing_console  # noqa: E402


class OperatorUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = render_marketing_console()
        cls.javascript = (ROOT / "src" / "marketing_machine" / "static" / "console.js").read_text(
            encoding="utf-8"
        )
        cls.css = (ROOT / "src" / "marketing_machine" / "static" / "console.css").read_text(
            encoding="utf-8"
        )
        cls.dashboard_smoke = (ROOT / "scripts" / "dashboard_visual_smoke.js").read_text(
            encoding="utf-8"
        )

    def test_mobile_campaign_scroller_is_named_and_keyboard_focusable(self):
        self.assertIn(
            'id="overviewCampaigns" role="region" aria-label="Kampagnenübersicht"',
            self.html,
        )
        self.assertIn('aria-live="polite" tabindex="0"', self.html)

    def test_ready_content_has_governed_postiz_draft_handoff(self):
        self.assertIn('brief.status === "ready_to_schedule"', self.javascript)
        self.assertIn("In Postiz als Entwurf übergeben", self.javascript)
        self.assertIn('post("/workflows/route-scheduler-draft"', self.javascript)
        self.assertIn("dry_run: !readiness.live", self.javascript)
        self.assertIn("metadata.external_writes_enabled === true", self.javascript)
        self.assertIn("postizCheck.configured === true", self.javascript)
        self.assertIn("postizCheck.write_ready === true", self.javascript)
        self.assertIn("postizCheck.contract_verified === true", self.javascript)
        self.assertIn(
            'live: state.approvalReadinessVerified\n        && capabilityCanRun("scheduler_handoff")',
            self.javascript,
        )
        self.assertNotIn("live: externalWritesEnabled && phaseReady", self.javascript)
        readiness_block = self.javascript.split("function postizWriteReadiness()", 1)[1].split(
            "function latestSchedulerHandoff", 1
        )[0]
        self.assertNotIn("used_successfully === true", readiness_block)
        self.assertIn('id="confirmPostizHandoff" required', self.javascript)
        self.assertIn("niemals veröffentlicht", self.javascript)
        self.assertIn("Das Übergabeprotokoll ist nicht erreichbar", self.javascript)
        self.assertIn("state.outboxAvailable = outbox.unavailable !== true", self.javascript)

    def test_console_never_embeds_or_sends_a_mutation_secret(self):
        self.assertNotIn("MARKETING_MACHINE_MUTATION_TOKEN", self.javascript)
        self.assertNotIn("X-WAMOCON-Mutation-Token", self.javascript)
        self.assertNotIn("X-WAMOCON-Actor", self.javascript)
        self.assertNotIn("X-WAMOCON-Edge-Attestation", self.javascript)
        self.assertNotRegex(self.javascript, re.compile(r"Bearer\s+[A-Za-z0-9._~-]{12,}"))
        self.assertIn('headers: { "Content-Type": "application/json"', self.javascript)

    def test_human_identity_is_bound_to_protected_session(self):
        self.assertIn('request("/session")', self.javascript)
        self.assertIn('session.authentication !== "edge_attested"', self.javascript)
        self.assertIn("requireAuthenticatedActor", self.javascript)
        self.assertIn('id="sessionIdentity"', self.html)
        self.assertRegex(self.html, r'id="analyticsOperator"[^>]*readonly')
        self.assertRegex(self.html, r'id="analyticsCorrectionOperator"[^>]*readonly')
        for dynamic_field in ("reviewerName", "revisionEditor", "mediaReviewer"):
            self.assertRegex(self.javascript, rf'id="{dynamic_field}"[^>]*readonly')
        self.assertNotIn("wamoconReviewerName", self.javascript)
        self.assertNotIn("wamoconAnalyticsOperator", self.javascript)
        self.assertNotIn("localStorage", self.javascript)

    def test_dashboard_smoke_uses_env_only_auth_without_logging_it(self):
        self.assertIn("process.env.MARKETING_MACHINE_MUTATION_TOKEN", self.dashboard_smoke)
        self.assertIn('extraHTTPHeaders["X-WAMOCON-Mutation-Token"] = mutationToken', self.dashboard_smoke)
        self.assertIn('extraHTTPHeaders["X-WAMOCON-Actor"]', self.dashboard_smoke)
        self.assertIn('extraHTTPHeaders["X-WAMOCON-Edge-Attestation"]', self.dashboard_smoke)
        self.assertIn('assertSuccessfulApiGet(context, "/session"', self.dashboard_smoke)
        self.assertIn("extraHTTPHeaders", self.dashboard_smoke)
        self.assertNotIn("console.log(mutationToken", self.dashboard_smoke)
        self.assertNotIn("token: mutationToken", self.dashboard_smoke)
        for contract in (
            "/campaigns",
            "/workflows/states?limit=100",
            "/integrations/status",
            "/workflows/phase-status",
            "/workflows/outbox",
            "/workflows/analytics/due",
        ):
            self.assertIn(contract, self.dashboard_smoke)
        self.assertIn("assertSuccessfulBrowserGet", self.dashboard_smoke)
        self.assertIn("assertSuccessfulApiGet", self.dashboard_smoke)
        self.assertIn("final_setup_desktop.png", self.dashboard_smoke)

    def test_outbox_states_are_operator_readable_and_auditable(self):
        self.assertIn('id="outboxList"', self.html)
        self.assertIn("delivery_unknown", self.javascript)
        self.assertIn("Abgleich erforderlich", self.javascript)
        self.assertIn("Nicht erneut senden", self.javascript)
        self.assertNotIn("Anbieter-Referenz", self.javascript)
        self.assertNotIn("item.external_reference", self.javascript)
        self.assertNotIn("route.reason", self.javascript)
        self.assertIn("item.updated_at || item.created_at", self.javascript)
        self.assertIn("provider-badge", self.css)

    def test_attempted_postiz_handoffs_offer_reconciliation_not_blind_retry(self):
        self.assertIn("Status mit Postiz abgleichen", self.javascript)
        self.assertIn('post("/workflows/reconcile-postiz", { route_id: routeId })', self.javascript)
        self.assertIn('["sent", "delivery_unknown", "confirmed"].includes(item.status)', self.javascript)
        self.assertIn("Kein erneutes Senden möglich", self.javascript)
        self.assertIn("Ein erneutes Senden wird nicht angeboten", self.javascript)
        self.assertIn("await refreshCore();", self.javascript)
        self.assertIn("await refreshApprovals();", self.javascript)
        self.assertIn("await refreshResults();", self.javascript)

    def test_instagram_reel_media_is_audited_and_gates_handoff(self):
        self.assertIn("isInstagramReel", self.javascript)
        self.assertIn("postiz_media_ready", self.javascript)
        self.assertIn("Benannte Person ordnet das freigegebene Video zu", self.javascript)
        for field_id in (
            "mediaAssetId",
            "mediaOriginalFile",
            "postizMediaId",
            "postizMediaPath",
            "mediaSha256",
            "mediaReviewer",
            "mediaApprovedAt",
            "mediaSourceRef",
            "mediaPreviewRef",
            "mediaConsentRefs",
            "mediaBrandCheck",
            "mediaFactCheck",
            "mediaPrivacyCheck",
            "mediaDisclosureCheck",
        ):
            self.assertIn(field_id, self.javascript)
        for contract_field in (
            'media_type: "video"',
            'verification_method: "operator_postiz_ui"',
            "preview_ref:",
            "brand_check_passed:",
            "fact_check_passed:",
            "privacy_check_passed:",
            "ai_disclosure_check_passed:",
            "supersedes_asset_id:",
        ):
            self.assertIn(contract_field, self.javascript)
        self.assertIn('post("/workflows/content-media-asset", payload)', self.javascript)
        self.assertIn("const assetVersion = mediaState.assets.length + 1", self.javascript)
        self.assertIn('const assetSuffix = `-postiz-video-v${assetVersion}`', self.javascript)
        self.assertIn(
            'response.asset?.checksum_scope === "approved_local_artifact_and_exact_postiz_path"',
            self.javascript,
        )
        self.assertNotIn(
            'response.asset?.checksum_scope === "approved_local_artifact"',
            self.javascript,
        )
        self.assertIn('post("/workflows/content-media-asset/revoke", payload)', self.javascript)
        self.assertIn("MEDIENZUORDNUNG", self.javascript)
        self.assertIn("hasExactProviderMediaProof", self.javascript)
        self.assertIn("provider_verification_valid === true", self.javascript)
        self.assertIn("Bei Postiz exakt best\u00e4tigt", self.javascript)
        self.assertIn("Anbieterpr\u00fcfung fehlt", self.javascript)
        self.assertIn("Video ersetzen", self.javascript)
        self.assertIn("Freigabe widerrufen", self.javascript)
        self.assertIn("frozenMediaRouteStatuses", self.javascript)
        self.assertIn("welches bereits freigegebene Video zu diesem Inhalt gehört", self.javascript)
        self.assertIn("bestätigt die Zuordnung zum freigegebenen Video", self.javascript)
        self.assertNotIn("Dateivergleich", self.javascript)
        self.assertNotIn("eindeutige Prüfung", self.javascript)
        self.assertIn("fingerprintLocalFile", self.javascript)
        self.assertIn('type="hidden" id="mediaAssetId"', self.javascript)
        self.assertIn('type="hidden" id="mediaSha256"', self.javascript)
        self.assertNotIn("Interne Asset-ID", self.javascript)
        self.assertNotIn("SHA-256 der lokal freigegebenen", self.javascript)

    def test_media_readiness_fails_closed_for_legacy_and_mismatched_assets(self):
        if not shutil.which("node"):
            self.skipTest("node is not available")

        helper_start = self.javascript.index("  function isInstagramReel(value) {")
        helper_end = self.javascript.index("\n  const routeCopy", helper_start)
        helpers = self.javascript[helper_start:helper_end]
        probe = f"""
const state = {{ recent: [{{ content_id: "legacy", postiz_media_ready: true }}] }};
{helpers}
const digest = "a".repeat(64);
const url = "https://uploads.postiz.example/video.mp4";
const exact = {{
  status: "approved", media_type: "video", postiz_media_id: "postiz-video",
  postiz_path: url, sha256: digest, provider_verified: true,
  provider_verification_valid: true,
  provider_verification_method: "postiz_public_url_sha256",
  provider_sha256: digest, provider_path: url,
}};
const legacy = {{
  status: "approved", media_type: "video", postiz_media_id: "legacy-video",
  postiz_path: url, sha256: digest, provider_verified: true,
  provider_verification_valid: false,
}};
const mismatch = {{ ...exact, provider_path: "https://uploads.postiz.example/other.mp4" }};
const payload = (asset) => ({{
  brief: {{ channel: "Instagram", format: "Reel" }},
  approved_media_assets: [asset], postiz_media_ready: true,
}});
process.stdout.write(JSON.stringify({{
  exact: mediaStateFor("legacy", payload(exact)),
  legacy: mediaStateFor("legacy", payload(legacy)),
  mismatch: mediaStateFor("legacy", payload(mismatch)),
}}));
"""
        result = subprocess.run(
            ["node", "-e", probe],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        states = json.loads(result.stdout)
        self.assertTrue(states["exact"]["postiz_media_ready"])
        self.assertEqual(states["exact"]["provider_verified_media_count"], 1)
        self.assertFalse(states["legacy"]["postiz_media_ready"])
        self.assertEqual(states["legacy"]["provider_verified_media_count"], 0)
        self.assertFalse(states["mismatch"]["postiz_media_ready"])

    def test_unverified_legacy_asset_card_is_never_labeled_ready(self):
        if not shutil.which("node"):
            self.skipTest("node is not available")

        verifier_start = self.javascript.index("  function hasExactProviderMediaProof(asset) {")
        verifier_end = self.javascript.index("\n  function mediaStateFor", verifier_start)
        verifier = self.javascript[verifier_start:verifier_end]
        markup_start = self.javascript.index("  function mediaAssetSummaryMarkup(")
        markup_end = self.javascript.index("\n  async function revokePostizMedia", markup_start)
        markup_helper = self.javascript[markup_start:markup_end]
        probe = f"""
const state = {{ selectedReviewId: "legacy", outbox: [] }};
function mediaAssetsFrozen() {{ return false; }}
function trustedMediaHref(value) {{ return String(value || ""); }}
function escapeHtml(value) {{ return String(value ?? ""); }}
function formatDateTime() {{ return "13.07.2026"; }}
{verifier}
{markup_helper}
const digest = "a".repeat(64);
const url = "https://uploads.postiz.example/video.mp4";
const legacy = {{
  asset_id: "legacy-video", status: "approved", media_type: "video",
  postiz_media_id: "legacy-postiz-video", postiz_path: url, sha256: digest,
  provider_verified: true, provider_verification_valid: false,
}};
const exact = {{
  ...legacy, asset_id: "exact-video", provider_verification_valid: true,
  provider_verification_method: "postiz_public_url_sha256",
  provider_sha256: digest, provider_path: url,
}};
process.stdout.write(JSON.stringify({{
  legacy: mediaAssetSummaryMarkup({{ id: "legacy" }}, {{ active_assets: [legacy] }}, ""),
  exact: mediaAssetSummaryMarkup({{ id: "exact" }}, {{ active_assets: [exact] }}, ""),
}}));
"""
        result = subprocess.run(
            ["node", "-e", probe],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        markup = json.loads(result.stdout)
        missing_copy = "Anbieterpr\u00fcfung fehlt"
        ready_copy = "Bei Postiz exakt best\u00e4tigt"
        blocked_copy = "Noch nicht \u00fcbergabebereit"
        self.assertIn(missing_copy, markup["legacy"])
        self.assertIn(blocked_copy, markup["legacy"])
        self.assertNotIn(ready_copy, markup["legacy"])
        self.assertIn(ready_copy, markup["exact"])
        self.assertNotIn(missing_copy, markup["exact"])

    def test_partial_readiness_copy_distinguishes_proven_ai_from_open_source_evidence(self):
        self.assertIn("controlledTextEvidenceMessage", self.javascript)
        self.assertIn("Die lokale KI wurde erfolgreich eingesetzt", self.javascript)
        self.assertIn("bis zur vollständigen Quellenprüfung gesperrt", self.javascript)
        self.assertNotIn("noch nicht durch erfolgreiche Nutzung belegt", self.javascript)

    def test_trend_cards_explain_the_exact_business_reason_for_source_holds(self):
        self.assertIn("Warum gesperrt?", self.javascript)
        self.assertIn("unabhängige Quelle", self.javascript)
        self.assertIn("kein verlässlicher Datumsbeleg im gewählten Zeitraum", self.javascript)
        self.assertIn("darf nicht als Trend bezeichnet werden", self.javascript)

    def test_k4_media_can_be_collected_before_final_review_and_every_decision_needs_a_note(self):
        self.assertIn("peopleEvidenceRequired", self.javascript)
        self.assertIn("peopleEvidenceReady", self.javascript)
        self.assertIn("Freigabe noch gesperrt", self.javascript)
        self.assertIn("Registrieren Sie zuerst das echte Video", self.javascript)
        self.assertIn('$("approvalNotes")?.setAttribute("required", "required")', self.javascript)
        self.assertIn("Freigabe- oder Überarbeitungsentscheidung begründen", self.javascript)

    def test_results_show_all_due_windows_and_audited_manual_entry(self):
        self.assertIn('id="analyticsDueList"', self.html)
        self.assertIn('const reviewWindows = ["72h", "7d", "14d", "30d"]', self.javascript)
        self.assertIn("/workflows/analytics/due?review_window=", self.javascript)
        required_fields = (
            "analyticsContentLabel",
            "analyticsReviewWindow",
            "analyticsPeriodStart",
            "analyticsPeriodEnd",
            "analyticsRetrievedAt",
            "analyticsOperator",
            "analyticsAttributionRule",
        )
        for field_id in required_fields:
            self.assertRegex(self.html, rf'id="{field_id}"[^>]*required')
        self.assertRegex(self.html, r'id="analyticsContentId"[^>]*type="hidden"|type="hidden"[^>]*id="analyticsContentId"')
        self.assertRegex(self.html, r'id="analyticsSourceRef"[^>]*type="hidden"|type="hidden"[^>]*id="analyticsSourceRef"')
        self.assertIn('if (!payload.content_id) return "Bitte zuerst eine fällige Auswertung auswählen."', self.javascript)
        self.assertIn('source_ref: $("analyticsSourceRef").value.trim() || evidence[0]?.ref || ""', self.javascript)
        self.assertIn('type="hidden" id="analyticsSnapshotSha256"', self.html)
        for field_id in (
            "analyticsEvidenceEngagementFile",
            "analyticsEvidenceLandingFile",
            "analyticsEvidenceCrmFile",
        ):
            self.assertIn(f'id="{field_id}"', self.html)
        self.assertNotIn("SHA-256 des Exports", self.html)
        self.assertIn("bleibt auf diesem Gerät", self.html)
        self.assertIn('id="analyticsSelectionGate"', self.html)
        self.assertRegex(self.html, r'id="analyticsEntryForm"[^>]*hidden')
        self.assertIn("setAnalyticsEntryVisible(Boolean(contentId))", self.javascript)
        self.assertIn('!$("analyticsContentId")?.value.trim()', self.javascript)
        self.assertIn("fehlende Belege ergänzen", self.javascript)

    def test_business_readiness_is_fail_closed_and_hides_infrastructure(self):
        self.assertIn('id="businessGuard"', self.html)
        self.assertIn("business_capabilities", self.javascript)
        readiness_block = self.javascript.split("function applyBusinessReadiness()", 1)[1].split(
            "function isInstagramReel", 1
        )[0]
        self.assertNotIn("state.phases.status", readiness_block)
        self.assertIn("controlledTextRun", readiness_block)
        self.assertIn("Neue Erstellung pausiert", self.javascript)
        self.assertIn("Welche Marketingarbeit ist heute möglich?", self.html)
        setup_block = self.javascript.split("function renderSetup()", 1)[1].split(
            "async function refreshCore", 1
        )[0]
        for infrastructure_name in ("n8n", "Ollama", "Comfy", "Firecrawl", "Grafana"):
            self.assertNotIn(infrastructure_name, setup_block)
        self.assertNotIn("technicalStatus", self.html + self.javascript)
        self.assertNotIn("JSON.stringify(item)", self.javascript)
        self.assertNotIn("console.error", self.javascript)

    def test_business_actions_use_their_own_confirmed_capability(self):
        self.assertIn('capabilityReady("research")', self.javascript)
        self.assertIn('capabilityReady("content_generation")', self.javascript)
        self.assertIn('capabilityCanRun("research")', self.javascript)
        self.assertIn('capabilityCanRun("content_generation")', self.javascript)
        self.assertIn('capabilityCanRun("approval")', self.javascript)
        self.assertIn('capabilityCanRun("scheduler_handoff")', self.javascript)
        self.assertIn(
            '$("runTrendScan").disabled = !state.selectedCampaign || !researchCanRun',
            self.javascript,
        )
        self.assertIn(
            '$("approveConcept").disabled = !state.selectedVariant || !contentCanRun',
            self.javascript,
        )
        self.assertIn('$("requestRevision").disabled = !approvalCanRun', self.javascript)
        self.assertIn(
            'button.disabled = !approvalCanRun || button.dataset.approvalPrerequisites !== "true"',
            self.javascript,
        )
        self.assertIn('button.disabled = !schedulerCanRun', self.javascript)
        self.assertIn('$("mediaSubmit").dataset.fileReady !== "true"', self.javascript)
        self.assertIn(
            "releaseReady: actorReady && capability.ready === true",
            self.javascript,
        )
        self.assertIn(
            "actionRunnable: actorReady && capability.can_run === true",
            self.javascript,
        )
        self.assertIn(
            'generation.status === "ai_generated" && generation.fallback_used === false',
            self.javascript,
        )
        self.assertIn("nicht mit dem freigegebenen Standard erstellt", self.javascript)
        self.assertIn("90–100: markengerecht", self.javascript)
        self.assertIn("Nur Vorschau · noch nichts gesendet", self.javascript)
        self.assertNotIn("kein externer Schreibvorgang", self.javascript)

    def test_business_truth_guards_studio_attention_evidence_and_unknown_states(self):
        self.assertIn('id="studioCampaignSummary"', self.html)
        self.assertIn("renderStudioCampaignSummary", self.javascript)
        self.assertIn("resetTrendSelection", self.javascript)
        self.assertIn("resetConceptSelection", self.javascript)
        self.assertIn("studioIdentityMatches", self.javascript)
        for identity_check in (
            "response.run_id !== trendRun.id",
            "concept.run_id !== runId",
            "responseBrief.trend_run_id !== runId",
        ):
            self.assertIn(identity_check, self.javascript)
        self.assertIn('const readyToSchedule = currentItems.filter((item) => item.status === "ready_to_schedule")', self.javascript)
        self.assertIn("reviewQueue.length + readyToSchedule.length", self.javascript)
        self.assertIn('$("navReviewCount").textContent = "–"', self.javascript)
        self.assertIn("Arbeitsstand unbekannt", self.javascript)
        self.assertIn("internalEvidenceMarkup", self.javascript)
        self.assertIn("vault_verified === true", self.javascript)
        self.assertIn('id="factCheck" ${evidenceInspectable ? "" : "disabled"}', self.javascript)
        self.assertIn('id="trendSourceGate"', self.html)
        self.assertIn("selectedTrendPlatforms().length === 0", self.javascript)
        self.assertIn("governed_media_job_unavailable", (ROOT / "src" / "marketing_machine" / "phases.py").read_text(encoding="utf-8"))
        self.assertIn("Assets werden extern erstellt", self.javascript)
        self.assertIn("box-shadow: 0 0 0 5px var(--teal)", self.css)

    def test_business_language_and_accessibility_hide_internal_contract_values(self):
        self.assertIn('return labels[String(value).toLowerCase()] || "Prüfung erforderlich"', self.javascript)
        self.assertIn('return labels[String(value || "").toLowerCase()] || "Kampagneninhalt"', self.javascript)
        self.assertIn('aria-current="page"', self.html)
        self.assertIn('role="progressbar"', self.html)
        self.assertIn('aria-pressed="${state.selectedVariant?.id === variant.id}"', self.javascript)
        self.assertIn('button.setAttribute("aria-pressed", String(selected))', self.javascript)
        self.assertIn('item.setAttribute("aria-current", "step")', self.javascript)
        self.assertIn('heading?.focus({ preventScroll: true })', self.javascript)
        self.assertIn("KI-Entwurf", self.html)
        self.assertNotIn("Auswahl zur Freigabe", self.html)

    def test_local_file_guard_checks_size_before_reading_bytes(self):
        guard = self.javascript.split("async function fingerprintLocalFile", 1)[1].split(
            "async function verifySelectedFile", 1
        )[0]
        self.assertIn("100 * 1024 * 1024", guard)
        self.assertLess(guard.index("file.size > maxBytes"), guard.index("file.arrayBuffer()"))
        self.assertIn("größer als 100 MB", self.javascript)

    def test_manual_analytics_payload_matches_provenance_contract(self):
        for field in (
            'source_system: "manual"',
            "source_ref:",
            "period_start:",
            "period_end:",
            "retrieved_at:",
            "operator:",
            "attribution_rule:",
            "snapshot_sha256:",
            "comments_from_target_buyers:",
            "qualified_leads:",
            "landing_page_conversions:",
            "pipeline_value_eur:",
            "evidence:",
            "metric_fields:",
        ):
            self.assertIn(field, self.javascript)
        self.assertIn('"/workflows/analytics-review/correct" : "/workflows/analytics-review"', self.javascript)
        self.assertIn("analyticsEvidenceConfirmed", self.javascript)
        self.assertIn("provenanceConfirmed", self.javascript)
        self.assertIn("Antwort ohne Herkunftsbestätigung", self.javascript)

    def test_analytics_correction_is_prefilled_and_audited(self):
        for field_id in (
            "analyticsCorrectionPanel",
            "analyticsSupersedesFingerprint",
            "analyticsCorrectionOperator",
            "analyticsCorrectedAt",
            "analyticsCorrectionReason",
        ):
            self.assertIn(f'id="{field_id}"', self.html)
        self.assertIn("analyticsRecordCanBeCorrected", self.javascript)
        self.assertIn("Object.hasOwn(item, field)", self.javascript)
        self.assertIn("Messung korrigieren", self.javascript)
        self.assertIn("supersedes_fingerprint:", self.javascript)
        self.assertIn("correction_reason:", self.javascript)
        self.assertIn("correction_operator:", self.javascript)
        self.assertIn("corrected_at:", self.javascript)

    def test_operator_assets_remain_parseable(self):
        if not shutil.which("node"):
            self.skipTest("node is not available")
        for relative_path in (
            "src/marketing_machine/static/console.js",
            "scripts/dashboard_visual_smoke.js",
            "scripts/operator_ui_isolated_smoke.js",
            "scripts/trend_studio_user_flow_smoke.js",
            "scripts/ui_truth_focused_smoke.js",
        ):
            result = subprocess.run(
                ["node", "--check", str(ROOT / relative_path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
