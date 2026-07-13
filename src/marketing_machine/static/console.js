(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const state = {
    route: "overview",
    studioStep: 1,
    campaigns: [],
    recent: [],
    integrations: null,
    phases: null,
    businessCapabilities: {},
    selectedCampaign: null,
    trendRun: null,
    selectedTrend: null,
    concept: null,
    selectedVariant: null,
    selectedReviewId: "",
    outbox: [],
    outboxAvailable: false,
    campaignsAvailable: false,
    recentAvailable: false,
    approvalDataAvailable: false,
    approvalReadinessVerified: false,
    reconciliations: {},
    performance: [],
    analyticsCorrection: null,
    session: { authenticated: false, actor: "", authentication: "", checked: false, error: "" },
  };

  const reviewAttentionStatuses = new Set([
    "needs_human_review",
    "revision_requested",
    "needs_evidence",
    "blocked",
  ]);

  function currentContentVersions(items) {
    const rows = Array.isArray(items)
      ? items.filter((item) => item && typeof item === "object")
      : [];
    const recordsById = new Map(rows
      .map((item) => [String(item.content_id || "").trim(), item])
      .filter(([contentId]) => Boolean(contentId)));
    const supersededIds = new Set();
    rows.forEach((item) => {
      const contentId = String(item.content_id || "").trim();
      const sourceId = String(item.revision_source?.content_id || "").trim();
      const sourceRevision = item.revision_source?.revision;
      const childRevision = item.state_revision;
      const predecessor = recordsById.get(sourceId);
      const childCampaign = String(item.campaign_id || "").trim().toLowerCase();
      const predecessorCampaign = String(predecessor?.campaign_id || "").trim().toLowerCase();
      if (sourceId
        && sourceId !== contentId
        && predecessor
        && Number.isInteger(sourceRevision)
        && sourceRevision >= 1
        && Number.isInteger(childRevision)
        && childRevision >= 1
        && Number.isInteger(predecessor.state_revision)
        && predecessor.state_revision === sourceRevision
        && /^k[1-5]$/.test(childCampaign)
        && childCampaign === predecessorCampaign) {
        supersededIds.add(sourceId);
      }
    });
    return rows.filter((item) => !supersededIds.has(String(item.content_id || "").trim()));
  }

  function reviewAttentionItems(items) {
    return currentContentVersions(items).filter((item) => reviewAttentionStatuses.has(item.status));
  }

  function authenticatedActor() {
    return state.session.authenticated === true && state.session.authentication === "edge_attested"
      ? String(state.session.actor || "").trim()
      : "";
  }

  function requireAuthenticatedActor(action) {
    const actor = authenticatedActor();
    if (actor) return actor;
    showToast(`${action} ist gesperrt: Bitte über die geschützte Anmeldung neu anmelden.`);
    return "";
  }

  function renderSessionIdentity() {
    const target = $("sessionIdentity");
    if (!target) return;
    const actor = authenticatedActor();
    target.className = `session-chip ${actor ? "is-authenticated" : "is-blocked"}`;
    target.innerHTML = actor
      ? `<span class="signal signal-ok"></span><span>Angemeldet: <strong>${escapeHtml(actor)}</strong></span>`
      : `<span class="signal signal-bad"></span><span>Anmeldung erforderlich</span>`;
    ["analyticsOperator", "analyticsCorrectionOperator"].forEach((id) => {
      const input = $(id);
      if (!input) return;
      input.value = actor;
      input.readOnly = true;
    });
    if ($("submitAnalytics")) $("submitAnalytics").disabled = !actor || !$("analyticsContentId")?.value.trim();
  }

  async function refreshSession() {
    try {
      const session = await request("/session");
      const actor = String(session.actor || "").trim();
      if (session.authenticated !== true || session.authentication !== "edge_attested" || !actor) {
        throw new Error("Die Anmeldung wurde nicht als geschützte, benannte Person bestätigt.");
      }
      state.session = { authenticated: true, actor, authentication: "edge_attested", checked: true, error: "" };
    } catch (error) {
      state.session = { authenticated: false, actor: "", authentication: "", checked: true, error: error.message || String(error) };
    }
    renderSessionIdentity();
    applyBusinessReadiness();
  }

  function businessCapability(name) {
    const item = state.businessCapabilities?.[name];
    if (item && typeof item === "object") return item;
    return {
      ready: false,
      can_run: false,
      available_for_controlled_run: false,
      status: "blocked",
      reason_code: "readiness_not_confirmed",
      business_message: "Die Arbeitsfreigabe konnte noch nicht bestätigt werden.",
    };
  }

  function capabilityReady(name) {
    return businessCapability(name).ready === true;
  }

  function capabilityCanRun(name) {
    return businessCapability(name).can_run === true;
  }

  function selectedTrendPlatforms() {
    return [...document.querySelectorAll('input[name="trendPlatform"]:checked')]
      .map((input) => input.value);
  }

  function updateTrendSourceSelection() {
    const selectedCount = selectedTrendPlatforms().length;
    const note = $("trendSourceGate");
    if (note) {
      note.classList.toggle("is-missing", selectedCount === 0);
      note.textContent = selectedCount
        ? `${selectedCount} öffentliche Quelle${selectedCount === 1 ? "" : "n"} ausgewählt.`
        : "Mindestens eine öffentliche Quelle ist erforderlich.";
    }
    applyBusinessReadiness();
  }

  function controlledTextEvidenceMessage(researchReady, contentReady) {
    if (contentReady && !researchReady) {
      return "Die lokale KI wurde erfolgreich eingesetzt. Aktuelle Aussagen bleiben bis zur vollständigen Quellenprüfung gesperrt.";
    }
    if (researchReady && !contentReady) {
      return "Die Recherche wurde erfolgreich belegt. Die lokale KI kann kontrolliert geprüft werden, bevor neue Entwürfe als bereit gelten.";
    }
    return "Recherche und lokale KI sind erreichbar. Starten Sie die erste kontrollierte Nutzung bewusst mit einer Kampagne.";
  }

  function applyBusinessReadiness() {
    const actorReady = Boolean(authenticatedActor());
    const researchReady = actorReady && capabilityReady("research");
    const researchCanRun = actorReady && capabilityCanRun("research");
    const contentReady = actorReady && capabilityReady("content_generation");
    const contentCanRun = actorReady && capabilityCanRun("content_generation");
    const approvalCanRun = actorReady && capabilityCanRun("approval");
    const schedulerCanRun = actorReady && capabilityCanRun("scheduler_handoff");
    const guard = $("businessGuard");
    const textReleaseProven = researchReady && contentReady;
    const controlledTextRun = researchCanRun && contentCanRun;
    const weeklyPlanReady = researchReady && contentCanRun;
    const anyTextRun = researchCanRun || contentCanRun;
    const controlledTextEvidence = controlledTextEvidenceMessage(researchReady, contentReady);

    if (guard) {
      guard.className = `business-guard ${textReleaseProven ? "is-ready" : anyTextRun ? "" : "is-blocked"}`;
      guard.innerHTML = textReleaseProven
        ? `<span class="signal signal-ok"></span><div><strong>Bereit für neue Inhalte</strong><p>Recherche und lokale KI wurden erfolgreich geprüft. Menschliche Freigabe bleibt Pflicht.</p></div><button class="text-button" type="button" data-route="setup">Status ansehen →</button>`
        : controlledTextRun
          ? `<span class="signal signal-warn"></span><div><strong>Kontrollierter Prüflauf möglich</strong><p>${escapeHtml(controlledTextEvidence)}</p></div><button class="text-button" type="button" data-route="setup">Prüfstand ansehen →</button>`
          : anyTextRun
            ? `<span class="signal signal-warn"></span><div><strong>Ein Prüfschritt ist möglich</strong><p>${researchCanRun ? "Die öffentliche Recherche kann kontrolliert geprüft werden; die KI-Erstellung ist noch nicht verfügbar." : "Die lokale KI kann kontrolliert geprüft werden; eine öffentliche Recherchequelle fehlt noch."}</p></div><button class="text-button" type="button" data-route="setup">Nächsten Schritt ansehen →</button>`
            : `<span class="signal signal-bad"></span><div><strong>Neue Erstellung pausiert</strong><p>Bestehende Entwürfe und Ergebnisse bleiben lesbar. Prüfen Sie Anmeldung und verfügbare Arbeitswege.</p></div><button class="text-button" type="button" data-route="setup">Grund ansehen →</button>`;
      guard.querySelector("[data-route]")?.addEventListener("click", () => setRoute("setup"));
    }

    if ($("createWeeklyPlan")) $("createWeeklyPlan").disabled = !weeklyPlanReady;
    if ($("toResearch")) $("toResearch").disabled = !state.selectedCampaign || !researchCanRun;
    if ($("runTrendScan")) $("runTrendScan").disabled = !state.selectedCampaign || !researchCanRun || selectedTrendPlatforms().length === 0;
    if ($("generateConcepts")) $("generateConcepts").disabled = !state.selectedTrend || !researchCanRun;
    if ($("toIdeas")) $("toIdeas").disabled = !state.selectedTrend || !researchCanRun;
    if ($("toReview")) $("toReview").disabled = !state.selectedVariant || !contentCanRun;
    if ($("approveConcept")) $("approveConcept").disabled = !state.selectedVariant || !contentCanRun;
    if ($("submitAnalytics")) $("submitAnalytics").disabled = !actorReady || !$("analyticsContentId")?.value.trim();

    document.querySelectorAll("[data-campaign-action]").forEach((button) => {
      const campaign = state.campaigns.find((item) => item.id === button.dataset.campaignAction);
      const action = campaign?.next_action?.kind || "prepare";
      if (["create", "prepare", "research"].includes(action)) {
        button.disabled = action === "research"
          ? !researchCanRun
          : action === "create"
            ? !contentCanRun
            : !researchCanRun;
        if (button.disabled) button.title = "Derzeit nicht verfügbar: Die sichere Arbeitsfreigabe fehlt.";
        else button.removeAttribute("title");
      }
    });

    document.querySelectorAll("#approvalForm button[type=submit]").forEach((button) => {
      button.disabled = !approvalCanRun || button.dataset.approvalPrerequisites !== "true";
    });
    if ($("requestRevision")) $("requestRevision").disabled = !approvalCanRun;
    document.querySelectorAll("#revisionForm button[type=submit]").forEach((button) => {
      button.disabled = !contentCanRun;
    });
    document.querySelectorAll("#schedulerHandoffForm button").forEach((button) => {
      button.disabled = !schedulerCanRun;
    });
    if ($("mediaSubmit")) {
      $("mediaSubmit").disabled = !approvalCanRun || $("mediaSubmit").dataset.fileReady !== "true";
    }
  }

  function isInstagramReel(value) {
    const channel = String(value?.channel || "").trim().toLowerCase();
    const format = String(value?.format || "").trim().toLowerCase();
    return channel.includes("instagram") && format.includes("reel");
  }

  function hasExactProviderMediaProof(asset) {
    const approvedSha = String(asset?.sha256 || "").trim().toLowerCase();
    const providerSha = String(asset?.provider_sha256 || "").trim().toLowerCase();
    const approvedPath = String(asset?.postiz_path || "").trim();
    const providerPath = String(asset?.provider_path || "").trim();
    return asset?.status === "approved"
      && asset?.provider_verification_valid === true
      && asset?.provider_verified === true
      && asset?.provider_verification_method === "postiz_public_url_sha256"
      && Boolean(String(asset?.postiz_media_id || "").trim())
      && /^[a-f0-9]{64}$/.test(approvedSha)
      && providerSha === approvedSha
      && Boolean(approvedPath)
      && providerPath === approvedPath;
  }

  function mediaStateFor(contentId, payload = null) {
    const summary = state.recent.find((item) => item.content_id === contentId) || {};
    const assets = Array.isArray(payload?.approved_media_assets)
      ? payload.approved_media_assets.filter((item) => item && typeof item === "object")
      : [];
    const activeAssets = assets.filter((item) => item.status === "approved");
    const verifiedActiveAssets = activeAssets.filter(hasExactProviderMediaProof);
    const payloadHasReadiness = typeof payload?.postiz_media_ready === "boolean";
    const content = payload?.brief || summary;
    const reel = isInstagramReel(content);
    const instagram = String(content?.channel || "").trim().toLowerCase().includes("instagram");
    const exactAssetReadiness = reel
      ? verifiedActiveAssets.some((item) => item.media_type === "video")
      : instagram
        ? verifiedActiveAssets.length > 0
        : true;
    const serverReadiness = payloadHasReadiness
      ? payload.postiz_media_ready === true
      : summary.postiz_media_ready === true;
    return {
      postiz_media_ready: serverReadiness && (payload ? exactAssetReadiness : true),
      approved_media_count: payload
        ? activeAssets.length
        : Number(summary.approved_media_count ?? 0),
      provider_verified_media_count: verifiedActiveAssets.length,
      assets,
      active_assets: activeAssets,
      verified_active_assets: verifiedActiveAssets,
    };
  }

  const routeCopy = {
    overview: ["MARKETING-ARBEITSPLATZ", "Guten Morgen.", "Hier sehen Sie, was heute wirklich Aufmerksamkeit braucht."],
    campaigns: ["KAMPAGNEN-PORTFOLIO", "Fünf Kampagnen.", "Ziele, Quellenlage und Content-Fortschritt auf einen Blick."],
    studio: ["CONTENT STUDIO", "Von der Quelle zum Content.", "Recherchieren, Richtungen vergleichen und bewusst auswählen."],
    approvals: ["FREIGABEN", "Der menschliche Qualitätscheck.", "Beleg, Marke, Datenschutz und KI-Kennzeichnung vor der Planung."],
    results: ["ERGEBNISSE", "Aus Signal wird Entscheidung.", "Lernen, verbessern, skalieren – oder bewusst stoppen."],
    setup: ["ARBEITSFÄHIGKEIT", "Was ist heute möglich?", "Fachliche Möglichkeiten und nächste Schritte – technische Details übernimmt die Betreuung."],
  };

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function safeUrl(value) {
    const raw = String(value || "").trim();
    if (!/^https?:\/\//i.test(raw)) return "";
    try {
      const url = new URL(raw);
      const hasUserinfo = (raw.match(/^https?:\/\/([^/?#]*)/i)?.[1] || "").includes("@");
      const host = url.hostname.toLowerCase().replace(/^\[|\]$/g, "").replace(/\.$/, "");
      const ipv4 = host.match(/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/)?.slice(1).map(Number);
      const privateIpv4 = ipv4 && (
        ipv4.some((part) => part > 255)
        || ipv4[0] === 0
        || ipv4[0] === 10
        || ipv4[0] === 127
        || (ipv4[0] === 100 && ipv4[1] >= 64 && ipv4[1] <= 127)
        || (ipv4[0] === 169 && ipv4[1] === 254)
        || (ipv4[0] === 172 && ipv4[1] >= 16 && ipv4[1] <= 31)
        || (ipv4[0] === 192 && ipv4[1] === 0)
        || (ipv4[0] === 192 && ipv4[1] === 168)
        || (ipv4[0] === 198 && [18, 19].includes(ipv4[1]))
        || (ipv4[0] === 198 && ipv4[1] === 51 && ipv4[2] === 100)
        || (ipv4[0] === 203 && ipv4[1] === 0 && ipv4[2] === 113)
        || ipv4[0] >= 224
      );
      const privateIpv6 = host.includes(":") && (
        host === "::"
        || host === "::1"
        || host.startsWith("fc")
        || host.startsWith("fd")
        || /^fe[89ab]/.test(host)
        || host.startsWith("::ffff:")
      );
      const privateSuffixes = [
        ".localhost", ".local", ".localdomain", ".internal", ".intranet",
        ".private", ".lan", ".home", ".home.arpa", ".corp",
        ".example", ".invalid", ".test", ".onion",
      ];
      const labels = host.split(".");
      const privateName = !host
        || host === "localhost"
        || host === "0.0.0.0"
        || privateSuffixes.some((suffix) => host.endsWith(suffix))
        || (!host.includes(":") && (
          labels.length < 2
          || labels.some((label) => !/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/i.test(label))
        ));
      if (!["http:", "https:"].includes(url.protocol) || hasUserinfo || url.username || url.password || privateIpv4 || privateIpv6 || privateName) return "";
      return url.href;
    } catch (_) {
      return "";
    }
  }

  function friendlyStatus(value) {
    const labels = {
      active: "Aktiv",
      planned: "Geplant",
      completed: "Abgeschlossen",
      paused: "Pausiert",
      drafting: "KI erstellt Entwurf",
      needs_evidence: "Beleg fehlt",
      needs_human_review: "Freigabe nötig",
      revision_requested: "Überarbeitung",
      approved: "Freigegeben",
      ready_to_schedule: "Bereit zur Planung",
      scheduled: "Geplant",
      published: "Veröffentlicht",
      blocked: "Blockiert",
      verified_sources: "Quellen verifiziert",
      verified_recent: "Aktuell verifiziert",
      needs_source_verification: "Quellenprüfung nötig",
      needs_live_sources: "Live-Quellen fehlen",
      requires_live_sources: "Nicht als Trend belegt",
      not_run: "Noch nicht recherchiert",
      prepared: "Vorbereitet",
      sent: "Übergeben",
      confirmed: "Bestätigt",
      reconciled: "Abgeglichen",
      reconciled_failed: "Anbieter meldet Fehler",
      draft_created: "Entwurf bestätigt",
      sending: "Übergabe läuft",
      delivery_unknown: "Ausgang unklar",
      failed: "Fehlgeschlagen",
      failed_definite: "Nicht übergeben",
      failed_safe_to_retry: "Erneute Entscheidung möglich",
      rate_limited: "Vorübergehend pausiert",
      confirmed_not_created: "Kein externer Entwurf angelegt",
      absence_unconfirmed: "Abgleich noch nicht eindeutig",
      reconciliation_pending: "Abgleich ausstehend",
      pending_second_confirmation: "Zweite Bestätigung ausstehend",
      authorized_retry: "Erneute Übergabe freigegeben",
      duplicate_prevented: "Doppelte Übergabe verhindert",
      scale: "Skalieren",
      iterate: "Verbessern",
      stop: "Stoppen",
      fix_landing_page: "Landingpage verbessern",
      fix_audience_or_offer: "Zielgruppe/Angebot prüfen",
      wait_for_more_data: "Weitere Daten abwarten",
      consent_required: "Einwilligung einholen",
      contact_missing: "Kontaktdaten ergänzen",
      manual_source_review: "Quelle fachlich prüfen",
      sales_follow_up: "Vertrieb meldet sich",
      manual_qualification: "Reaktion qualifizieren",
      nurture_or_disqualify: "Weiterentwickeln oder aussortieren",
      sales_handoff: "An Vertrieb übergeben",
      nurture: "Weiterentwickeln",
      disqualify: "Nicht weiterverfolgen",
      ready: "Bereit",
      partial: "Prüfung offen",
      degraded: "Eingeschränkt",
      unavailable: "Nicht verfügbar",
      pending: "Ausstehend",
    };
    if (!value) return "–";
    return labels[String(value).toLowerCase()] || "Prüfung erforderlich";
  }

  function statusClass(value) {
    if (["approved", "ready_to_schedule", "scheduled", "published", "verified_sources", "verified_recent", "sent", "confirmed", "draft_created", "scale"].includes(value)) return "ok";
    if (["blocked", "needs_evidence", "stop", "failed", "failed_definite", "delivery_unknown", "reconciled_failed"].includes(value)) return "bad";
    return "";
  }

  function reviewWindowLabel(value) {
    return { "72h": "72 Stunden", "7d": "7 Tage", "14d": "14 Tage", "30d": "30 Tage" }[value] || "Messfenster";
  }

  function friendlyRisk(value) {
    const labels = {
      outcome_claims_require_evidence: "Ergebnis-, Effizienz- und Entscheidungssicherheits-Aussagen benötigen einen gesonderten Beleg.",
      people_consent_and_real_assets_required: "Vor Freigabe echte Medien einsetzen und Einwilligungen aller sichtbaren Personen dokumentieren.",
      architecture_and_compliance_claims_require_evidence: "Architektur-, Datenschutz- und Compliance-Aussagen benötigen einen gesonderten Beleg.",
      product_ui_and_outcome_claims_require_evidence: "Produktoberflächen und Ergebnisversprechen benötigen einen gesonderten Beleg.",
      individual_app_examples_require_evidence: "Einzelne App-Beispiele benötigen einen gesonderten Portfolio-Nachweis.",
    };
    return labels[value] || "Ein fachlicher Pflichtnachweis muss vor der Freigabe geprüft werden.";
  }

  function friendlyFormat(value) {
    const labels = {
      expert_post: "Fachbeitrag",
      carousel: "Carousel",
      portfolio_carousel: "Portfolio-Carousel",
      reel: "Reel",
      instagram_reel: "Instagram-Reel",
      short_video: "Kurzvideo",
      video: "Video",
      image: "Bildbeitrag",
      article: "Fachartikel",
      linkedin_post: "LinkedIn-Fachbeitrag",
    };
    return labels[String(value || "").toLowerCase()] || "Kampagneninhalt";
  }

  function friendlyDecisionReason(value) {
    const message = String(value || "").toLowerCase();
    if (message.includes("weak early signal")) return "Das frühe Signal ist noch schwach. Einstieg oder Vorschaubild gezielt testen.";
    if (message.includes("early signal exists")) return "Ein erstes Signal ist sichtbar. Für eine belastbare Entscheidung werden weitere Daten benötigt.";
    if (message.includes("clicks without leads")) return "Klicks führen noch nicht zu Leads. Zielseite und Angebot prüfen.";
    if (message.includes("reach without buyer")) return "Reichweite erreicht bisher zu wenige passende Interessenten. Zielgruppe und Botschaft schärfen.";
    if (message.includes("qualified") || message.includes("pipeline")) return "Geschäftlich relevante Reaktionen sind belegt. Erfolgreiche Elemente kontrolliert weiterverwenden.";
    if (message.includes("no useful")) return "Es liegt noch kein nützliches Geschäftssignal vor. Inhalt vorerst nicht ausweiten.";
    if (message.includes("30-day") || message.includes("30 day")) return "Das 30-Tage-Fenster ist geprüft. Die nächste Maßnahme folgt den belegten Geschäftssignalen.";
    if (message.includes("review window")) return "Die Entscheidung wurde für das gewählte Messfenster anhand der Geschäftsregeln getroffen.";
    return "Die Entscheidung wurde anhand der belegten Messwerte und Geschäftsregeln getroffen.";
  }

  function contentBusinessLabel(contentId, fallback = "Kampagneninhalt") {
    const item = state.recent.find((candidate) => candidate.content_id === contentId);
    return item?.campaign || item?.campaign_name || fallback;
  }

  function friendlyWorkflowError(value) {
    const message = String(value || "").toLowerCase();
    if (message.includes("ai-generated") || message.includes("generation provenance") || message.includes("model")) {
      return "Die lokale KI hat keinen verlässlich prüfbaren Entwurf geliefert. Bitte eine neue Version erstellen.";
    }
    if (message.includes("trend") || message.includes("source") || message.includes("citation") || message.includes("proof")) {
      return "Die Quellen sind nicht mehr ausreichend aktuell oder passen nicht vollständig zum Entwurf. Bitte neu recherchieren.";
    }
    if (message.includes("consent") || message.includes("people") || message.includes("media") || message.includes("einwilligung")) {
      return "Ein freigegebenes echtes Medium oder ein notwendiger Einwilligungsnachweis fehlt.";
    }
    if (message.includes("german brief") || message.includes("language")) {
      return "Der Entwurf enthält Formulierungen, die vor der Freigabe sprachlich überarbeitet werden müssen.";
    }
    if (message.includes("approval") || message.includes("human review")) {
      return "Die Freigabe ist noch nicht vollständig oder gehört nicht zu dieser Entwurfsversion.";
    }
    return "Eine Pflichtprüfung ist noch offen. Bitte den Entwurf überarbeiten oder die Recherche erneuern.";
  }

  function businessErrorMessage(error) {
    const message = String(error?.message || error || "").toLowerCase();
    if (message.startsWith("wochenplan gesperrt:")) return "Die Wochenplanung ist momentan pausiert. Bitte unter Arbeitsfähigkeit den nächsten fachlichen Schritt prüfen.";
    if (message.includes("actor") || message.includes("session") || message.includes("401") || message.includes("anmeld")) {
      return "Die geschützte Anmeldung ist nicht mehr gültig. Bitte neu anmelden; es wurde nichts verändert.";
    }
    if (message.includes("trend") || message.includes("source") || message.includes("citation")) {
      return "Die Recherche konnte nicht sicher bestätigt werden. Bitte Quellen und Zeitraum erneut prüfen.";
    }
    if (message.includes("generation") || message.includes("model") || message.includes("ai") || message.includes("ki")) {
      return "Die Ideen- und Texterstellung ist gerade nicht verlässlich verfügbar. Es wurde nichts zur Freigabe geschickt.";
    }
    if (message.includes("zu groß")) {
      return "Die Datei ist größer als 100 MB und kann im Browser nicht sicher geprüft werden. Bitte einen kleineren Export auswählen.";
    }
    if (message.includes("https")) {
      return "Die Datei konnte nicht sicher auf diesem Gerät geprüft werden. Bitte den geschützten Zugang neu öffnen und die Datei erneut auswählen.";
    }
    if (message.includes("datei")) return "Bitte eine gültige, nicht leere Datei auswählen.";
    if (message.includes("revision") || message.includes("conflict") || message.includes("already") || message.includes("409")) {
      return "Der Inhalt wurde zwischenzeitlich geändert. Bitte einmal aktualisieren und den aktuellen Stand prüfen.";
    }
    return "Die Aktion konnte nicht sicher abgeschlossen werden. Es wurde nichts verändert. Bitte aktualisieren und bei Wiederholung Marketing Operations informieren.";
  }

  async function fingerprintLocalFile(file, { maxBytes = 100 * 1024 * 1024 } = {}) {
    if (!(file instanceof File) || !file.size) throw new Error("Bitte eine nicht leere Datei auswählen.");
    if (file.size > maxBytes) throw new Error("Die ausgewählte Datei ist zu groß für die sichere Prüfung im Browser.");
    if (!globalThis.crypto?.subtle) throw new Error("Die sichere lokale Dateiprüfung benötigt die geschützte HTTPS-Verbindung.");
    const digest = await globalThis.crypto.subtle.digest("SHA-256", await file.arrayBuffer());
    return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
  }

  async function verifySelectedFile({ fileId, shaId, proofId, refId = "", submitId = "" }) {
    const fileInput = $(fileId);
    const shaInput = $(shaId);
    const proof = $(proofId);
    const submit = submitId ? $(submitId) : null;
    const file = fileInput?.files?.[0];
    if (shaInput) shaInput.value = "";
    if (submit) {
      submit.dataset.fileReady = "false";
      submit.disabled = true;
    }
    if (!file) {
      if (proof) {
        proof.className = "file-proof";
        proof.textContent = fileId === "mediaOriginalFile"
          ? "Noch keine lokale Originaldatei zugeordnet."
          : "Noch keine Belegdatei geprüft.";
      }
      return;
    }
    if (proof) {
      proof.className = "file-proof is-checking";
      proof.textContent = "Datei wird lokal geprüft …";
    }
    try {
      const fingerprint = await fingerprintLocalFile(file);
      if (fileInput.files?.[0] !== file) return;
      shaInput.value = fingerprint;
      if (refId && !$(refId).value.trim()) $(refId).value = file.name;
      if (proof) {
        proof.className = "file-proof is-ready";
        proof.textContent = `Lokale Datei durch Ihre Auswahl zugeordnet · ${file.name}`;
      }
      if (submit) submit.dataset.fileReady = "true";
    } catch (error) {
      fileInput.value = "";
      if (proof) {
        proof.className = "file-proof is-failed";
        proof.textContent = businessErrorMessage(error);
      }
    } finally {
      applyBusinessReadiness();
    }
  }

  function formatDate(value) {
    if (!value) return "–";
    const date = new Date(value.length === 10 ? `${value}T00:00:00` : value);
    if (Number.isNaN(date.getTime())) return value;
    return new Intl.DateTimeFormat("de-DE", { day: "2-digit", month: "short", year: "numeric" }).format(date);
  }

  function formatDateTime(value) {
    if (!value) return "–";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return new Intl.DateTimeFormat("de-DE", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).format(date);
  }

  function formatCurrency(value) {
    return new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR", maximumFractionDigits: 0 }).format(Number(value || 0));
  }

  function domainOf(value) {
    try { return new URL(value).hostname.replace(/^www\./, ""); } catch (_) { return "Quelle"; }
  }

  function showToast(message) {
    const toast = $("toast");
    toast.textContent = message;
    toast.classList.add("is-visible");
    clearTimeout(showToast.timeout);
    showToast.timeout = setTimeout(() => toast.classList.remove("is-visible"), 3200);
  }

  async function request(path, options = {}) {
    const response = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    const text = await response.text();
    let payload = {};
    try { payload = text ? JSON.parse(text) : {}; } catch (_) { payload = { detail: text }; }
    if (!response.ok) {
      const detail = typeof payload.detail === "string"
        ? payload.detail
        : typeof payload.detail?.message === "string"
          ? payload.detail.message
          : `request_failed_${response.status}`;
      throw new Error(detail || `HTTP ${response.status}`);
    }
    return payload;
  }

  function post(path, payload) {
    return request(path, { method: "POST", body: JSON.stringify(payload) });
  }

  function setRoute(route, { updateHash = true } = {}) {
    if (!routeCopy[route]) route = "overview";
    state.route = route;
    document.querySelectorAll("[data-view]").forEach((view) => view.classList.toggle("is-active", view.dataset.view === route));
    document.querySelectorAll("[data-route]").forEach((button) => button.classList.toggle("is-active", button.dataset.route === route));
    document.querySelectorAll(".primary-nav [data-route], .mobile-nav [data-route], .side-footer [data-route]").forEach((button) => {
      if (button.dataset.route === route) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    });
    const copy = routeCopy[route];
    $("pageEyebrow").textContent = copy[0];
    $("pageTitle").textContent = copy[1];
    $("pageSubtitle").textContent = copy[2];
    if (updateHash) history.replaceState(null, "", `#${route}`);
    // A route swap replaces the whole workspace. Reset immediately so the new
    // heading cannot remain hidden behind the sticky header while a previous
    // page's smooth-scroll animation is still running.
    window.scrollTo({ top: 0, behavior: "auto" });
    requestAnimationFrame(() => {
      const heading = $("pageTitle");
      heading?.setAttribute("tabindex", "-1");
      heading?.focus({ preventScroll: true });
    });
    if (route === "approvals") refreshApprovals().catch(handleError);
    if (route === "results") refreshResults().catch(handleError);
    if (route === "setup") refreshSetup().catch(handleError);
  }

  function setStudioStep(step) {
    state.studioStep = Number(step);
    document.querySelectorAll("[data-stage]").forEach((section) => {
      const active = Number(section.dataset.stage) === state.studioStep;
      section.classList.toggle("is-active", active);
      section.setAttribute("aria-hidden", String(!active));
    });
    document.querySelectorAll("[data-studio-step]").forEach((item) => {
      const number = Number(item.dataset.studioStep);
      item.classList.toggle("is-active", number === state.studioStep);
      item.classList.toggle("is-done", number < state.studioStep);
      if (number === state.studioStep) item.setAttribute("aria-current", "step");
      else item.removeAttribute("aria-current");
    });
    window.scrollTo({ top: 0, behavior: "auto" });
    requestAnimationFrame(() => {
      const heading = document.querySelector(`[data-stage="${state.studioStep}"] h2`);
      heading?.setAttribute("tabindex", "-1");
      heading?.focus({ preventScroll: true });
    });
  }

  function campaignCard(campaign) {
    const progress = campaign.content?.progress_percent || 0;
    const boundedProgress = Math.max(0, Math.min(100, Number(progress) || 0));
    const action = campaign.next_action || { kind: "create", label: "Content erstellen", detail: "Nächsten Schritt öffnen" };
    const progressMarkup = campaign.status === "planned"
      ? `<div class="progress-copy"><span>Start ${escapeHtml(formatDate(campaign.start_date))}</span><strong>Noch nicht im Wochenziel</strong></div>`
      : `<div class="progress-line" role="progressbar" aria-label="Fortschritt für ${escapeHtml(campaign.short_name)}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${boundedProgress}"><span style="width:${boundedProgress}%"></span></div><div class="progress-copy"><span>${campaign.content?.approved || 0}/${campaign.content?.effective_weekly_target ?? campaign.content?.weekly_target ?? campaign.weekly_target} freigegeben</span><strong>${boundedProgress}%</strong></div>`;
    return `
      <article class="campaign-card" style="--campaign-accent:${escapeHtml(campaign.accent)}">
        <div class="campaign-code"><span>${escapeHtml(campaign.code)}</span><span class="lifecycle ${escapeHtml(campaign.status)}">${escapeHtml(friendlyStatus(campaign.status))}</span></div>
        <h3>${escapeHtml(campaign.short_name)}</h3>
        <p class="persona">${escapeHtml(campaign.primary_persona)}</p>
        ${progressMarkup}
        <button class="next-action" type="button" data-campaign-action="${escapeHtml(campaign.id)}"><span>${escapeHtml(action.label)}<small>${escapeHtml(action.detail)}</small></span><b>→</b></button>
      </article>`;
  }

  function renderCampaigns() {
    if (!state.campaignsAvailable) {
      const unavailable = `<div class="notice notice-warn">Die Kampagnen konnten nicht geladen werden. Auswahl und Fortschritt sind derzeit unbekannt; bitte später erneut aktualisieren.</div>`;
      $("overviewCampaigns").innerHTML = unavailable;
      $("studioCampaignPicker").innerHTML = unavailable;
      $("campaignList").innerHTML = unavailable;
      renderStudioCampaignSummary();
      applyBusinessReadiness();
      return;
    }
    $("overviewCampaigns").innerHTML = state.campaigns.map(campaignCard).join("");
    $("studioCampaignPicker").innerHTML = state.campaigns.map((campaign) => `
      <button class="pick-card ${state.selectedCampaign?.id === campaign.id ? "is-selected" : ""}" style="--campaign-accent:${escapeHtml(campaign.accent)}" type="button" data-pick-campaign="${escapeHtml(campaign.id)}" aria-pressed="${state.selectedCampaign?.id === campaign.id}">
        <div class="campaign-code"><span>${escapeHtml(campaign.code)}</span><span class="lifecycle ${escapeHtml(campaign.status)}">${escapeHtml(friendlyStatus(campaign.status))}</span></div>
        <h3>${escapeHtml(campaign.short_name)}</h3>
        <p>${escapeHtml(campaign.primary_persona)} · Ausgabe: ${escapeHtml(campaign.default_channel)} · ${escapeHtml(friendlyFormat(campaign.default_format))}</p>
      </button>`).join("");
    $("campaignList").innerHTML = state.campaigns.map((campaign) => `
      <article class="campaign-row" style="--campaign-accent:${escapeHtml(campaign.accent)}">
        <div class="campaign-row-code">${escapeHtml(campaign.code)}</div>
        <div><h3>${escapeHtml(campaign.short_name)}</h3><p>${escapeHtml(campaign.description)}</p><div class="channel-list">${campaign.channels.slice(0, 4).map((channel) => `<span>${escapeHtml(channel)}</span>`).join("")}</div></div>
        <div><small>Zielgruppe & Angebot</small><strong>${escapeHtml(campaign.primary_persona)}</strong><p>${escapeHtml(campaign.offer)}</p></div>
        <div class="source-state"><small>Quellenlage</small><span class="status-tag ${statusClass(campaign.research?.status)}"><span class="signal ${["verified_sources", "verified_recent"].includes(campaign.research?.status) ? "signal-ok" : "signal-warn"}"></span>${escapeHtml(friendlyStatus(campaign.research?.status))}</span><p>${campaign.research?.last_run_at ? formatDate(campaign.research.last_run_at) : "Keine Live-Recherche"}</p></div>
        <div><small>${formatDate(campaign.start_date)} – ${formatDate(campaign.end_date)}</small>${campaign.status === "planned" ? `<p>Startet später · zählt noch nicht zum Wochenziel</p>` : `<div class="progress-line" role="progressbar" aria-label="Fortschritt für ${escapeHtml(campaign.short_name)}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.max(0, Math.min(100, Number(campaign.content?.progress_percent || 0)))}"><span style="width:${Math.max(0, Math.min(100, Number(campaign.content?.progress_percent || 0)))}%"></span></div><p>${campaign.content?.approved || 0}/${campaign.content?.effective_weekly_target ?? campaign.content?.weekly_target ?? campaign.weekly_target} Wochenziel</p>`}<button class="next-action" type="button" data-campaign-action="${escapeHtml(campaign.id)}"><span>${escapeHtml(campaign.next_action?.label || "Öffnen")}</span><b>→</b></button></div>
      </article>`).join("");
    bindCampaignActions();
    renderStudioCampaignSummary();
    applyBusinessReadiness();
  }

  function bindCampaignActions() {
    document.querySelectorAll("[data-pick-campaign]").forEach((button) => button.addEventListener("click", () => selectCampaign(button.dataset.pickCampaign)));
    document.querySelectorAll("[data-campaign-action]").forEach((button) => button.addEventListener("click", () => openCampaignAction(button.dataset.campaignAction)));
  }

  function openCampaignAction(campaignId) {
    selectCampaign(campaignId);
    const campaign = state.campaigns.find((item) => item.id === campaignId);
    const kind = campaign?.next_action?.kind || "prepare";
    if (["review", "blocked"].includes(kind)) {
      const candidate = reviewAttentionItems(state.recent).find((item) => item.campaign_id === campaignId);
      state.selectedReviewId = candidate?.content_id || "";
      setRoute("approvals");
      return;
    }
    if (["results", "measure"].includes(kind)) {
      setRoute("results");
      return;
    }
    setRoute("studio");
    setStudioStep(kind === "research" ? 2 : 1);
  }

  function renderStudioCampaignSummary() {
    const target = $("studioCampaignSummary");
    if (!target) return;
    const campaign = state.selectedCampaign;
    const selectionCurrent = Boolean(campaign && state.campaignsAvailable);
    target.hidden = !selectionCurrent;
    target.innerHTML = selectionCurrent
      ? `<span>${escapeHtml(campaign.code || campaign.id?.toUpperCase() || "K")}</span><div><strong>${escapeHtml(campaign.short_name || campaign.name || "Gewählte Kampagne")}</strong><small>${escapeHtml(campaign.primary_persona || "Zielgruppe offen")} · ${escapeHtml(campaign.default_channel || "Kanal offen")} · ${escapeHtml(friendlyFormat(campaign.default_format))}</small></div><em>Aktuelle Auswahl</em>`
      : "";
  }

  function resetConceptSelection({ promptChanged = false } = {}) {
    state.concept = null;
    state.selectedVariant = null;
    if ($("conceptResults")) $("conceptResults").innerHTML = "";
    if ($("selectedConceptReview")) $("selectedConceptReview").innerHTML = "";
    if ($("conceptGate")) {
      $("conceptGate").className = "notice notice-neutral";
      $("conceptGate").textContent = promptChanged
        ? "Ihre Vorgabe wurde geändert. Bereiten Sie die Richtungen erneut vor."
        : "Bereiten Sie vier belegte Richtungen vor. Die lokale KI erstellt erst nach Ihrer bewussten Auswahl den vollständigen Entwurf.";
    }
    if ($("toReview")) $("toReview").disabled = true;
    if ($("approveConcept")) $("approveConcept").disabled = true;
  }

  function resetTrendSelection({ inputsChanged = false } = {}) {
    state.trendRun = null;
    state.selectedTrend = null;
    resetConceptSelection();
    if ($("trendResults")) $("trendResults").innerHTML = "";
    if ($("researchGate")) {
      $("researchGate").className = "notice notice-neutral";
      $("researchGate").textContent = inputsChanged
        ? "Die Rechercheauswahl wurde geändert. Starten Sie die Recherche erneut, bevor Sie weitergehen."
        : "Starten Sie die Recherche. Ohne verifizierte Quellen bleibt die Trend-Weiterleitung gesperrt.";
    }
    if ($("toIdeas")) $("toIdeas").disabled = true;
  }

  function studioIdentityMatches({ campaignSourceId, runId = "", trendId = "" }) {
    return Boolean(
      state.selectedCampaign?.source_id === campaignSourceId
      && (!runId || state.trendRun?.id === runId)
      && (!trendId || state.selectedTrend?.id === trendId)
    );
  }

  function selectCampaign(campaignId) {
    state.selectedCampaign = state.campaigns.find((item) => item.id === campaignId) || null;
    resetTrendSelection();
    if ($("trendUserPrompt")) $("trendUserPrompt").value = "";
    renderCampaigns();
    renderStudioCampaignSummary();
    applyBusinessReadiness();
  }

  function renderAttentionQueue() {
    const items = [];
    if (!state.campaignsAvailable || !state.recentAvailable) {
      $("attentionCount").textContent = "Status unbekannt";
      $("attentionQueue").innerHTML = `<div class="attention-item"><span>!</span><div><strong>Arbeitsstand konnte nicht geladen werden</strong><small>Freigaben, Planungsaufgaben und Kampagnenfortschritt werden nicht als null gewertet. Bitte die Seite aktualisieren.</small></div><button type="button" data-attention-route="overview" aria-label="Arbeitsstand erneut öffnen">↻</button></div>`;
      $("navReviewCount").textContent = "–";
      $("reviewCount").textContent = "–";
      document.querySelector("[data-attention-route]")?.addEventListener("click", () => refreshCore().catch(handleError));
      return;
    }
    const currentItems = currentContentVersions(state.recent);
    const reviewQueue = reviewAttentionItems(state.recent);
    const readyReviewCount = reviewQueue.filter((item) => item.status === "needs_human_review").length;
    const blockedReviewCount = reviewQueue.length - readyReviewCount;
    const readyToSchedule = currentItems.filter((item) => item.status === "ready_to_schedule");
    const missingMedia = readyToSchedule.filter((item) => isInstagramReel(item) && item.postiz_media_ready !== true);
    const campaignsMissingSources = state.campaigns.filter((item) => item.status === "active" && !["verified_sources", "verified_recent"].includes(item.research?.status));
    if (readyReviewCount) items.push({ label: `${readyReviewCount} Entwurf${readyReviewCount === 1 ? "" : "e"} warten auf Freigabe`, detail: "Fakten, Datenschutz und Markenfit prüfen", route: "approvals" });
    if (blockedReviewCount) items.push({ label: `${blockedReviewCount} Entwurf${blockedReviewCount === 1 ? " braucht" : "e brauchen"} zuerst Klärung`, detail: "Fehlende Belege oder Überarbeitungen bearbeiten", route: "approvals" });
    if (readyToSchedule.length) items.push({ label: `${readyToSchedule.length} freigegebene${readyToSchedule.length === 1 ? "r Inhalt wartet" : " Inhalte warten"} auf Planung`, detail: missingMedia.length ? `${missingMedia.length} davon ${missingMedia.length === 1 ? "benötigt" : "benötigen"} zuerst ein freigegebenes Video` : "Als Entwurf an die Redaktionsplanung übergeben", route: "approvals" });
    campaignsMissingSources.forEach((campaign) => items.push({ label: `${campaign.code}: Live-Quellen fehlen`, detail: "Trend-Scan starten, bevor aktuelle Aussagen entstehen", route: "studio", campaign: campaign.id }));
    const openCount = reviewQueue.length + readyToSchedule.length + campaignsMissingSources.length;
    const visibleItems = items.length ? items : [{ label: "Alles Wesentliche ist erledigt", detail: "Für heute gibt es keine offenen Freigaben oder Blocker.", route: "campaigns" }];
    $("attentionCount").textContent = `${openCount} offen`;
    $("attentionQueue").innerHTML = visibleItems.slice(0, 5).map((item, index) => `
      <div class="attention-item"><span>${String(index + 1).padStart(2, "0")}</span><div><strong>${escapeHtml(item.label)}</strong><small>${escapeHtml(item.detail)}</small></div><button type="button" data-attention-route="${escapeHtml(item.route)}" data-attention-campaign="${escapeHtml(item.campaign || "")}" aria-label="${escapeHtml(item.label)} öffnen">→</button></div>`).join("");
    document.querySelectorAll("[data-attention-route]").forEach((button) => button.addEventListener("click", () => {
      if (button.dataset.attentionCampaign) selectCampaign(button.dataset.attentionCampaign);
      setRoute(button.dataset.attentionRoute);
    }));
    $("navReviewCount").textContent = String(reviewQueue.length + readyToSchedule.length);
    $("reviewCount").textContent = String(reviewQueue.length + readyToSchedule.length);
  }

  function renderRecent() {
    if (!state.recentAvailable || !state.campaignsAvailable) {
      $("recentWork").innerHTML = `<div class="notice notice-warn">Aktuelle Inhalte und Fortschritt konnten nicht geladen werden. Der Stand ist unbekannt; es wird kein falscher Nullwert angezeigt.</div>`;
      $("portfolioProgress").textContent = "–";
      $("portfolioProgressBar").style.width = "0%";
      $("portfolioProgressBar").parentElement?.removeAttribute("aria-valuenow");
      $("portfolioProgressBar").parentElement?.setAttribute("aria-valuetext", "Fortschritt derzeit unbekannt");
      $("portfolioProgressCopy").textContent = "Der aktuelle Wochenfortschritt ist derzeit nicht verfügbar.";
      return;
    }
    const visible = currentContentVersions(state.recent).slice(0, 6);
    $("recentWork").innerHTML = visible.length ? visible.map((item) => `
      <div class="work-item"><div><strong>${escapeHtml(item.campaign || "Kampagneninhalt")}</strong><small>${escapeHtml(friendlyFormat(item.format))} · ${formatDate(item.updated_at)}</small></div><span>${escapeHtml(item.channel || "Kanal offen")}</span><span class="status-tag ${statusClass(item.status)}">${escapeHtml(friendlyStatus(item.status))}</span><button class="text-button" type="button" data-open-review="${escapeHtml(item.content_id)}">Öffnen →</button></div>`).join("") : `<div class="empty-state" style="min-height:180px"><p>Noch keine echten Inhalte. Starten Sie im Content Studio.</p></div>`;
    document.querySelectorAll("[data-open-review]").forEach((button) => button.addEventListener("click", () => {
      state.selectedReviewId = button.dataset.openReview;
      setRoute("approvals");
    }));
    const activeCampaigns = state.campaigns.filter((item) => item.status === "active");
    const plannedCount = state.campaigns.filter((item) => item.status === "planned").length;
    const approved = activeCampaigns.reduce((sum, item) => sum + Number(item.content?.approved || 0), 0);
    const target = activeCampaigns.reduce((sum, item) => sum + Number(item.content?.effective_weekly_target ?? item.effective_weekly_target ?? item.content?.weekly_target ?? item.weekly_target ?? 0), 0);
    const progress = target ? Math.min(100, Math.round((approved / target) * 100)) : 0;
    $("portfolioProgress").textContent = `${progress}%`;
    $("portfolioProgressBar").style.width = `${progress}%`;
    $("portfolioProgressBar").parentElement?.setAttribute("aria-valuenow", String(progress));
    $("portfolioProgressBar").parentElement?.setAttribute("aria-valuetext", `${approved} von ${target} Inhalten freigegeben`);
    $("portfolioProgressCopy").textContent = `${approved} von ${target} Inhalten für ${activeCampaigns.length} aktive Kampagnen sind freigegeben.${plannedCount ? ` ${plannedCount} weitere Kampagne${plannedCount === 1 ? " startet" : "n starten"} später und ${plannedCount === 1 ? "zählt" : "zählen"} noch nicht zum Wochenziel.` : ""}`;
  }

  function verifiedTrend(trend) {
    return trend?.verification?.eligible_for_content === true;
  }

  function trendFitLabel(value) {
    const score = Number(value);
    if (!Number.isFinite(score)) return "Kampagnenpassung geprüft";
    if (score >= 75) return "Hohe Kampagnenpassung";
    if (score >= 50) return "Mittlere Kampagnenpassung";
    return "Begrenzte Kampagnenpassung";
  }

  function creativeDirectionLabel(value) {
    const label = String(value || "").trim();
    if (!label || label.includes("_") || label.length > 80) return "Redaktionelle Richtung";
    return label;
  }

  function citationsOf(value) {
    const candidates = value?.citations || value?.evidence || value?.sources || [];
    return Array.isArray(candidates) ? candidates.map((item) => ({
      title: item.title || item.name || item.claim || domainOf(item.url || item.source_ref),
      url: item.url || item.source_url || item.source_ref || "",
      publisher: item.publisher || item.domain || item.source || domainOf(item.url || item.source_ref),
      published_at: item.published_at || item.published || "",
      retrieved_at: item.retrieved_at || item.last_checked_at || "",
      snippet: item.snippet || item.description || item.excerpt || "",
    })) : [];
  }

  function citationMarkup(citations) {
    const publicSources = citations.filter((item) => safeUrl(item.url));
    if (!publicSources.length) return `<div class="notice notice-warn">Keine externe, anklickbare Quelle vorhanden.</div>`;
    return `<div class="citation-list">${publicSources.map((item) => `<div class="citation"><div><a href="${escapeHtml(safeUrl(item.url))}" target="_blank" rel="noopener noreferrer">${escapeHtml(item.title)}</a><small>${escapeHtml(item.publisher)}${item.published_at ? ` · ${formatDate(item.published_at)}` : ""}</small>${item.snippet ? `<small>${escapeHtml(item.snippet.slice(0, 220))}</small>` : ""}</div><span>↗</span></div>`).join("")}</div>`;
  }

  function internalEvidenceInspectable(item) {
    return Boolean(
      item?.vault_verified === true
      && item.approved_for_public_use === true
      && String(item.claim || "").trim()
      && String(item.source_ref || "").trim()
      && String(item.source_type || "").trim()
      && String(item.owner || "").trim()
      && String(item.vault_version || "").trim()
    );
  }

  function internalEvidenceMarkup(records) {
    const items = Array.isArray(records) ? records.filter((item) => item && typeof item === "object") : [];
    if (!items.length) return "";
    const typeLabels = {
      internal_campaign_brief: "Freigegebener Kampagnenbeleg",
      customer_story: "Kundenbeleg",
      employee_story: "Teambeleg",
      applicant_story: "Bewerberbeleg",
    };
    return `<div class="internal-evidence-list">${items.map((item) => {
      const inspectable = internalEvidenceInspectable(item);
      const version = String(item.vault_version || "").trim();
      const createdAt = String(item.created_at || "").trim();
      return `<article class="internal-evidence-card ${inspectable ? "" : "is-unverified"}"><strong>${escapeHtml(item.claim || "Interner Beleg ohne sichtbare Aussage")}</strong><dl><div><dt>Belegart</dt><dd>${escapeHtml(typeLabels[item.source_type] || item.source_type || "Nicht dokumentiert")}</dd></div><div><dt>Verantwortlich</dt><dd>${escapeHtml(item.owner || "Nicht dokumentiert")}</dd></div><div><dt>Referenz</dt><dd>${escapeHtml(item.source_ref || "Nicht dokumentiert")}</dd></div><div><dt>Stand</dt><dd>${escapeHtml(version ? `Version ${version}` : createdAt ? formatDate(createdAt) : "Nicht dokumentiert")}</dd></div></dl>${inspectable ? "" : `<small>Metadaten nicht vollständig bestätigt · Faktenprüfung gesperrt</small>`}</article>`;
    }).join("")}</div>`;
  }

  function reviewEvidenceInspectable(citations, records) {
    return citations.some((item) => Boolean(safeUrl(item.url)))
      || (Array.isArray(records) && records.some(internalEvidenceInspectable));
  }

  function productionPlanMarkup(brief) {
    const reel = brief.reel_output || {};
    const slides = Array.isArray(brief.channel_copy?.carousel_slides) ? brief.channel_copy.carousel_slides : [];
    const list = (label, items) => Array.isArray(items) && items.length
      ? `<div><strong>${escapeHtml(label)}</strong><ol>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ol></div>`
      : "";
    const hasReel = Boolean(reel.idea || reel.hook || reel.caption || (reel.script || []).length);
    const reelMarkup = hasReel ? `<section class="production-plan"><h4>Reel-Produktionsplan</h4><div class="production-meta"><p><strong>Idee</strong>${escapeHtml(reel.idea || "–")}</p><p><strong>Format</strong>${escapeHtml(reel.format || "–")}</p><p><strong>Hook</strong>${escapeHtml(reel.hook || "–")}</p></div><div class="production-lists">${list("Sprechtext / Beats", reel.script)}${list("Shotlist", reel.shot_list)}${list("On-Screen-Text", reel.on_screen_text)}</div><p><strong>Caption</strong>${escapeHtml(reel.caption || "–")}</p><p><strong>CTA</strong>${escapeHtml(reel.cta || brief.cta || "–")}</p><p><strong>Schnittnotizen</strong>${escapeHtml(reel.editing_notes || "–")}</p></section>` : "";
    const slideMarkup = slides.length ? `<section class="production-plan"><h4>Carousel-Slides</h4><ol>${slides.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ol></section>` : "";
    return reelMarkup + slideMarkup;
  }

  async function runTrendScan() {
    if (!state.selectedCampaign) return;
    const platforms = selectedTrendPlatforms();
    if (!platforms.length) {
      $("researchGate").className = "notice notice-bad";
      $("researchGate").textContent = "Wählen Sie mindestens eine öffentliche Quelle aus.";
      updateTrendSourceSelection();
      return;
    }
    const campaignSourceId = state.selectedCampaign.source_id;
    const requestId = globalThis.crypto?.randomUUID?.() || `console-${Date.now()}`;
    resetTrendSelection();
    const progress = $("researchProgress");
    progress.classList.remove("is-hidden");
    progress.setAttribute("aria-busy", "true");
    $("runTrendScan").disabled = true;
    $("researchGate").className = "notice notice-neutral";
    $("researchGate").textContent = "Recherche läuft. Ergebnisse werden erst nach Quellen- und Datumsprüfung freigegeben.";
    try {
      const response = await post("/workflows/trend-research", {
        request_id: requestId,
        lookback_days: Number($("trendLookback").value),
        campaign_ids: [campaignSourceId],
        platforms,
      });
      if (state.selectedCampaign?.source_id !== campaignSourceId) return;
      const trendRun = response.trend_run;
      const campaignResult = (trendRun?.campaigns || []).find((item) => item.campaign?.id === campaignSourceId);
      if (!trendRun?.id || response.run_id !== trendRun.id || !campaignResult) {
        throw new Error("Die Rechercheantwort passt nicht zur gewählten Kampagne. Bitte erneut recherchieren.");
      }
      state.trendRun = trendRun;
      renderTrendResults(campaignResult?.trends || []);
    } catch (error) {
      if (state.selectedCampaign?.source_id !== campaignSourceId) return;
      $("researchGate").className = "notice notice-bad";
      $("researchGate").textContent = businessErrorMessage(error);
      $("trendResults").innerHTML = "";
      handleError(error, false);
    } finally {
      progress.classList.add("is-hidden");
      progress.setAttribute("aria-busy", "false");
      applyBusinessReadiness();
    }
  }

  function renderTrendResults(trends) {
    state.selectedTrend = null;
    resetConceptSelection();
    const campaignSourceId = state.selectedCampaign?.source_id || "";
    const runId = state.trendRun?.id || "";
    $("toIdeas").disabled = true;
    const verified = trends.filter(verifiedTrend);
    if (!verified.length) {
      $("researchGate").className = "notice notice-warn";
      $("researchGate").textContent = "Keine ausreichend belegte aktuelle Entwicklung gefunden. Die Kampagnenidee bleibt als Evergreen-Hinweis sichtbar, kann aber nicht als Trend weiterverarbeitet werden.";
    } else {
      $("researchGate").className = "notice notice-ok";
      $("researchGate").textContent = `${verified.length} Trend${verified.length === 1 ? "" : "s"} mit mindestens zwei unabhängigen Quellen und aktuellem Datumsbeleg gefunden.`;
    }
    $("trendResults").innerHTML = trends.map((trend) => {
      const isVerified = verifiedTrend(trend);
      const citations = citationsOf(trend);
      const publicSourceCount = citations.filter((item) => safeUrl(item.url)).length;
      const verification = trend?.verification || {};
      const independentSourceCount = Number(
        verification.current_independent_source_count
          ?? verification.independent_source_count
          ?? publicSourceCount,
      );
      const minimumSources = Number(verification.minimum_independent_sources ?? 2);
      const recentSourceCount = Number(
        verification.current_recent_source_count
          ?? verification.dated_recent_count
          ?? verification.recent_source_count
          ?? 0,
      );
      const minimumRecentSources = Number(verification.minimum_recent_sources ?? 1);
      const verificationExplanation = isVerified
        ? ""
        : verification.status === "evergreen_unverified"
          ? "Es wurden keine ausreichend aktuellen öffentlichen Belege gefunden. Die Idee bleibt zeitlos und darf nicht als Trend bezeichnet werden."
          : independentSourceCount < minimumSources
            ? `${independentSourceCount} unabhängige Quelle${independentSourceCount === 1 ? "" : "n"} gefunden; mindestens ${minimumSources} sind erforderlich.`
            : recentSourceCount < minimumRecentSources
              ? "Mehrere unabhängige Quellen wurden gefunden, aber kein verlässlicher Datumsbeleg im gewählten Zeitraum."
              : "Die Quellenprüfung ist noch nicht vollständig. Die Idee darf deshalb nicht als aktuelle Entwicklung verwendet werden.";
      const publicPlatforms = (trend.platforms || []).filter((item) => String(item).toLowerCase() !== "internal");
      const contextLabel = publicPlatforms.length ? publicPlatforms.join(" · ") : "Evergreen-Hinweis";
      return `<article class="trend-card" data-trend-card="${escapeHtml(trend.id)}"><div class="trend-card-head"><div><h3>${escapeHtml(trend.topic || "Thema")}</h3><p>${escapeHtml(trend.angle || trend.campaign_fit || "")}</p></div><span class="status-tag ${isVerified ? "ok" : "bad"}">${isVerified ? "Verifiziert" : "Nicht als Trend belegt"}</span></div><div class="trend-meta"><span class="status-tag">${escapeHtml(trendFitLabel(trend.score))}</span><span class="status-tag">${independentSourceCount} unabhängige Quelle${independentSourceCount === 1 ? "" : "n"}</span><span class="status-tag">${escapeHtml(contextLabel)}</span></div>${isVerified ? "" : `<div class="notice notice-warn"><strong>Warum gesperrt?</strong><br>${escapeHtml(verificationExplanation)}</div>`}${citationMarkup(citations)}<button class="button ${isVerified ? "button-dark" : "button-quiet"}" type="button" data-select-trend="${escapeHtml(trend.id)}" aria-pressed="${state.selectedTrend?.id === trend.id}" ${isVerified ? "" : "disabled"}>${isVerified ? "Diesen Trend verwenden" : "Weiterleitung gesperrt"}</button></article>`;
    }).join("") || `<div class="notice notice-warn">Keine Ergebnisse. Die öffentliche Recherche ist derzeit nicht bestätigt; bitte unter Arbeitsfähigkeit prüfen.</div>`;
    document.querySelectorAll("[data-select-trend]").forEach((button) => button.addEventListener("click", () => {
      if (!studioIdentityMatches({ campaignSourceId, runId })) {
        resetTrendSelection({ inputsChanged: true });
        showToast("Die Kampagnen- oder Rechercheauswahl hat sich geändert. Bitte erneut recherchieren.");
        return;
      }
      state.selectedTrend = trends.find((item) => item.id === button.dataset.selectTrend) || null;
      resetConceptSelection();
      document.querySelectorAll("[data-trend-card]").forEach((card) => card.classList.toggle("is-selected", card.dataset.trendCard === button.dataset.selectTrend));
      document.querySelectorAll("[data-select-trend]").forEach((candidate) => candidate.setAttribute("aria-pressed", String(candidate === button)));
      $("toIdeas").disabled = !state.selectedTrend;
      applyBusinessReadiness();
    }));
  }

  async function generateConcepts() {
    if (!state.trendRun || !state.selectedTrend || !state.selectedCampaign) return;
    const campaignSourceId = state.selectedCampaign.source_id;
    const runId = state.trendRun.id;
    const trendId = state.selectedTrend.id;
    const userPrompt = $("trendUserPrompt").value.trim();
    resetConceptSelection();
    const progress = $("ideaProgress");
    progress.classList.remove("is-hidden");
    progress.setAttribute("aria-busy", "true");
    $("generateConcepts").disabled = true;
    try {
      const response = await post("/workflows/reel-concepts", {
        run_id: runId,
        campaign_id: campaignSourceId,
        trend_id: trendId,
        user_prompt: userPrompt,
        variant_count: 4,
      });
      if (!studioIdentityMatches({ campaignSourceId, runId, trendId })) return;
      const concept = response.concept;
      if (!concept?.id
        || concept.run_id !== runId
        || concept.campaign_id !== campaignSourceId
        || concept.trend_id !== trendId) {
        throw new Error("Die vorbereiteten Richtungen passen nicht mehr zur aktuellen Kampagnenauswahl.");
      }
      state.concept = concept;
      state.selectedVariant = null;
      renderConcepts();
      $("conceptGate").className = "notice notice-ok";
      $("conceptGate").textContent = "Vier belegte redaktionelle Richtungen sind bereit. Wählen Sie eine aus; erst danach erstellt die lokale KI den vollständigen Entwurf.";
    } catch (error) {
      if (!studioIdentityMatches({ campaignSourceId, runId, trendId })) return;
      $("conceptGate").className = "notice notice-bad";
      $("conceptGate").textContent = businessErrorMessage(error);
      handleError(error, false);
    } finally {
      progress.classList.add("is-hidden");
      progress.setAttribute("aria-busy", "false");
      applyBusinessReadiness();
    }
  }

  function conceptMarkup(variant, { selectable = true } = {}) {
    const beats = variant.beats || variant.script || variant.scene_script || [];
    const shots = variant.shot_list || variant.shots || [];
    const readableItem = (item, fields) => {
      if (typeof item === "string" || typeof item === "number") return String(item);
      if (!item || typeof item !== "object") return "Redaktioneller Baustein";
      for (const field of fields) if (typeof item[field] === "string" && item[field].trim()) return item[field];
      return "Redaktioneller Baustein";
    };
    const citations = citationsOf(variant).length ? citationsOf(variant) : citationsOf(state.selectedTrend || {});
    return `<article class="concept-card ${state.selectedVariant?.id === variant.id ? "is-selected" : ""}" data-concept-card="${escapeHtml(variant.id)}">
      ${selectable ? `<button class="concept-select" type="button" data-select-variant="${escapeHtml(variant.id)}" aria-pressed="${state.selectedVariant?.id === variant.id}"><span class="radio-mark"></span><div><span class="status-tag">${escapeHtml(creativeDirectionLabel(variant.format))}</span><h3>${escapeHtml(variant.idea || variant.title || "Content-Idee")}</h3><p>${escapeHtml(variant.hook || "")}</p></div></button>` : `<div class="concept-select"><span class="radio-mark"></span><div><span class="status-tag">${escapeHtml(creativeDirectionLabel(variant.format))}</span><h3>${escapeHtml(variant.idea || variant.title || "Content-Idee")}</h3><p>${escapeHtml(variant.hook || "")}</p></div></div>`}
      <div class="concept-body">
        <div class="artifact"><label>Ablauf / Kernpunkte</label>${Array.isArray(beats) ? `<ol>${beats.map((item) => `<li>${escapeHtml(readableItem(item, ["text", "voiceover", "point"]))}</li>`).join("")}</ol>` : `<p>${escapeHtml(beats)}</p>`}</div>
        <div class="artifact"><label>Visual-Ideen</label>${Array.isArray(shots) ? `<ul>${shots.map((item) => `<li>${escapeHtml(readableItem(item, ["shot", "visual", "text"]))}</li>`).join("")}</ul>` : `<p>${escapeHtml(shots)}</p>`}</div>
        <div class="artifact"><label>Darstellung & Text</label><p>${escapeHtml(variant.animation_notes || variant.editing_notes || variant.on_screen_text || "–")}</p></div>
        <div class="artifact"><label>Caption</label><div class="caption-preview">${escapeHtml(variant.caption || "–")}</div></div>
        <div class="artifact"><label>CTA</label><p><strong>${escapeHtml(variant.cta || "–")}</strong></p></div>
        <div class="artifact"><label>Referenzen</label>${citationMarkup(citations)}</div>
      </div>
    </article>`;
  }

  function renderConcepts() {
    const variants = state.concept?.variants || [];
    $("conceptResults").innerHTML = variants.map((variant) => conceptMarkup(variant)).join("");
    $("toReview").disabled = !state.selectedVariant;
    document.querySelectorAll("[data-select-variant]").forEach((button) => button.addEventListener("click", () => {
      state.selectedVariant = variants.find((item) => item.id === button.dataset.selectVariant) || null;
      renderConcepts();
      applyBusinessReadiness();
    }));
  }

  function renderSelectedReview() {
    $("selectedConceptReview").innerHTML = state.selectedVariant ? conceptMarkup(state.selectedVariant, { selectable: false }) : `<div class="notice notice-warn">Keine Variante ausgewählt.</div>`;
  }

  async function sendConceptToReview() {
    if (!requireAuthenticatedActor("Erstellung des KI-Entwurfs")) return;
    if (!state.concept || !state.selectedVariant) return;
    const campaignSourceId = state.selectedCampaign?.source_id || "";
    const campaignId = state.selectedCampaign?.id || "";
    const runId = state.trendRun?.id || "";
    const trendId = state.selectedTrend?.id || "";
    const conceptId = state.concept.id;
    const variantId = state.selectedVariant.id;
    if (!studioIdentityMatches({ campaignSourceId, runId, trendId })
      || state.concept.run_id !== runId
      || state.concept.campaign_id !== campaignSourceId
      || state.concept.trend_id !== trendId) {
      resetConceptSelection({ promptChanged: true });
      showToast("Die Auswahl passt nicht mehr zur aktuellen Recherche. Bitte Richtungen erneut vorbereiten.");
      return;
    }
    $("approveConcept").disabled = true;
    const progress = $("finalDraftProgress");
    progress?.classList.remove("is-hidden");
    progress?.setAttribute("aria-busy", "true");
    try {
      const response = await post(`/workflows/reel-concepts/${encodeURIComponent(conceptId)}/approve`, { variant_id: variantId });
      if (!studioIdentityMatches({ campaignSourceId, runId, trendId })) return;
      const responseBrief = response.state?.brief || {};
      if (response.concept_id !== conceptId
        || responseBrief.trend_run_id !== runId
        || responseBrief.trend_id !== trendId
        || ![campaignId, campaignSourceId].includes(responseBrief.campaign_id)) {
        throw new Error("Der erzeugte Entwurf passt nicht zur bestätigten Kampagnenauswahl.");
      }
      state.selectedReviewId = response.content_id;
      if (response.state?.brief?.generation?.status !== "ai_generated") {
        throw new Error("AI generation was not confirmed");
      }
      showToast("Der KI-Entwurf ist erstellt und liegt sicher zur menschlichen Prüfung bereit.");
      await refreshCore();
      setRoute("approvals");
    } catch (error) {
      let blockedDraft = null;
      try {
        await refreshCore();
        const campaignIds = new Set([state.selectedCampaign?.id, state.selectedCampaign?.source_id].filter(Boolean));
        blockedDraft = currentContentVersions(state.recent).find((item) => campaignIds.has(item.campaign_id) && ["blocked", "revision_requested"].includes(item.status));
      } catch (_) {
        // The original business-safe error below remains the useful outcome.
      }
      if (blockedDraft) {
        state.selectedReviewId = blockedDraft.content_id;
        showToast("Der Entwurf wurde sicher gesperrt. Öffnen Sie ihn unter Freigaben und erstellen Sie dort eine neue Version.");
        setRoute("approvals");
      } else {
        handleError(error);
      }
    } finally {
      progress?.classList.add("is-hidden");
      progress?.setAttribute("aria-busy", "false");
      applyBusinessReadiness();
    }
  }

  function postizWriteReadiness() {
    const publishingPhase = (state.phases?.phases || []).find((item) => item.id === "09_publishing_plane") || {};
    const metadata = publishingPhase.metadata || {};
    const postizCheck = (state.integrations?.checks || []).find((item) => item.name === "postiz") || {};
    const externalWritesEnabled = metadata.external_writes_enabled === true;
    const configured = postizCheck.configured === true;
    const integrationReady = postizCheck.write_ready === true;
    const contractVerified = postizCheck.contract_verified === true;
    return {
      // `used_successfully` is completion evidence, not a prerequisite for the
      // first governed handoff. Requiring it here would create a dry-run-only
      // deadlock. The API still validates the approved draft payload itself.
      live: state.approvalReadinessVerified
        && capabilityCanRun("scheduler_handoff")
        && externalWritesEnabled
        && configured
        && integrationReady
        && contractVerified,
      externalWritesEnabled,
      configured,
      integrationReady,
      contractVerified,
    };
  }

  function latestSchedulerHandoff(contentId) {
    return state.outbox
      .filter((item) => item.kind === "scheduler_draft" && item.source_id === contentId)
      .sort((left, right) => String(right.updated_at || right.created_at || "").localeCompare(String(left.updated_at || left.created_at || "")))[0] || null;
  }

  function handoffStatusCopy(route) {
    if (!route) return "Noch keine Übergabe vorbereitet.";
    const target = route.target === "postiz" ? "Postiz" : route.target === "crm" ? "das CRM" : "die Redaktionsplanung";
    if (route.status === "sent") return route.target === "postiz"
      ? "Als Entwurf an Postiz übergeben. Die Veröffentlichung bleibt in Postiz gesperrt, bis ein Mensch dort final freigibt."
      : `An ${target} übergeben.`;
    if (route.status === "confirmed") return route.target === "postiz" ? "Mit Postiz abgeglichen: Der Anbieter hat den Entwurf bestätigt." : `Mit ${target} abgeglichen.`;
    if (route.status === "prepared") return `Nur vorbereitet: ${target} wurde nicht verändert.`;
    if (route.status === "sending") return "Übergabe läuft. Bitte nicht erneut auslösen, bis der Status geklärt ist.";
    if (route.status === "delivery_unknown") return `Ausgang unklar: Nicht erneut senden. Zuerst in ${target} abgleichen, ob der Datensatz angelegt wurde.`;
    if (route.status === "blocked") return "Die Übergabe ist sicher gesperrt. Bitte Arbeitsfähigkeit und Freigabestand prüfen.";
    if (route.status === "failed") return "Die Übergabe wurde nicht bestätigt. Marketing Operations prüft den Vorgang.";
    if (route.status === "failed_safe_to_retry") return "Der Anbieter hat den Versuch eindeutig abgelehnt. Nach fachlicher Prüfung kann eine benannte Person erneut entscheiden.";
    if (route.status === "rate_limited") return "Der Anbieter nimmt vorübergehend keine weitere Übergabe an. Bitte den Status später erneut prüfen.";
    if (route.status === "confirmed_not_created") return "Der Abgleich bestätigt: Es wurde kein externer Entwurf angelegt.";
    if (["reconciliation_pending", "pending_second_confirmation"].includes(route.status)) return "Der Ausgang wird noch sicher abgeglichen. Bitte nicht erneut übergeben.";
    if (route.status === "authorized_retry") return "Eine benannte Person hat eine erneute Übergabe nach Prüfung freigegeben.";
    return "Der Übergabestand wird fachlich geprüft.";
  }

  function handoffSummaryMarkup(route) {
    if (!route) return `<div class="inline-result">Noch kein Übergabeversuch protokolliert.</div>`;
    return `<div class="inline-result ${route.status === "sent" ? "is-ok" : route.status === "delivery_unknown" || route.status === "blocked" || route.status === "failed" ? "is-bad" : "is-warn"}">
      <strong>${escapeHtml(friendlyStatus(route.status))}</strong>
      <span>${escapeHtml(handoffStatusCopy(route))}</span>
      <small>${route.dry_run ? "Nur intern vorbereitet" : "Externer Entwurf"} · ${formatDateTime(route.updated_at || route.created_at)}</small>
    </div>`;
  }

  function reconciliationConfirmationMarkup(routeId) {
    const result = state.reconciliations[routeId];
    if (!result) return "";
    if (result.error) return `<div class="inline-result is-bad"><strong>Abgleich nicht bestätigt</strong><span>${escapeHtml(result.error)}</span></div>`;
    const statusCopy = result.provider_status === "published"
      ? "Postiz bestätigt die Veröffentlichung. Fällige Messfenster werden nun vom Veröffentlichungszeitpunkt berechnet."
      : result.provider_status === "confirmed_not_created"
        ? "Postiz bestätigt, dass kein externer Entwurf angelegt wurde. Eine erneute Entscheidung kann jetzt sicher vorbereitet werden."
        : result.provider_status === "absence_unconfirmed"
          ? "Postiz konnte noch nicht eindeutig bestätigen, ob ein Entwurf existiert. Bitte nicht erneut übergeben."
          : result.provider_status === "failed"
            ? "Postiz meldet einen fehlgeschlagenen Entwurf. Marketing Operations prüft den nächsten sicheren Schritt."
            : "Postiz bestätigt, dass der Entwurf existiert. Veröffentlicht ist er noch nicht.";
    const tone = result.provider_status === "failed" ? "is-bad" : result.provider_status === "absence_unconfirmed" ? "is-warn" : "is-ok";
    return `<div class="inline-result ${tone}"><strong>${escapeHtml(friendlyStatus(result.provider_status))}</strong><span>${escapeHtml(statusCopy)}</span><small>Nur gelesen; es wurde nichts erneut gesendet.</small></div>`;
  }

  function bindPostizReconciliationActions() {
    document.querySelectorAll("[data-reconcile-postiz]").forEach((button) => {
      if (button.dataset.reconciliationBound === "true") return;
      button.dataset.reconciliationBound = "true";
      button.addEventListener("click", () => reconcilePostizRoute(button.dataset.reconcilePostiz, button));
    });
  }

  async function reconcilePostizRoute(routeId, button) {
    if (!requireAuthenticatedActor("Postiz-Abgleich")) return;
    button.disabled = true;
    const originalLabel = button.textContent;
    button.textContent = "Postiz wird gelesen …";
    let response;
    try {
      response = await post("/workflows/reconcile-postiz", { route_id: routeId });
    } catch (error) {
      state.reconciliations[routeId] = { error: businessErrorMessage(error) };
      document.querySelectorAll("[data-reconciliation-result]").forEach((target) => {
        if (target.dataset.reconciliationResult === routeId) target.innerHTML = reconciliationConfirmationMarkup(routeId);
      });
      handleError(error);
      button.disabled = false;
      button.textContent = originalLabel;
      return;
    }
    state.reconciliations[routeId] = {
      provider_status: response.provider_status || response.lifecycle?.provider_status || "confirmed",
      provider_post_id: response.provider_post_id || response.lifecycle?.state?.lifecycle?.provider_post_id || "",
    };
    showToast(response.provider_status === "published" ? "Veröffentlichung durch Postiz bestätigt." : "Postiz-Entwurf bestätigt – noch nicht veröffentlicht.");
    try {
      await refreshCore();
      await refreshApprovals();
      await refreshResults();
    } catch (error) {
      console.warn("Die Anbieterbestätigung wurde gespeichert; die Ansicht konnte nicht vollständig aktualisiert werden.");
      document.querySelectorAll("[data-reconciliation-result]").forEach((target) => {
        if (target.dataset.reconciliationResult === routeId) target.innerHTML = reconciliationConfirmationMarkup(routeId);
      });
      showToast("Postiz wurde bestätigt; die Ansicht konnte nicht vollständig aktualisiert werden.");
    }
    if (button.isConnected) {
      button.disabled = false;
      button.textContent = originalLabel;
    }
  }

  function mediaRegistrationMarkup(brief, mediaState, savedReviewer, { supersedesAssetId = "" } = {}) {
    const contentId = brief.id || state.selectedReviewId;
    const replacing = Boolean(supersedesAssetId);
    const assetVersion = mediaState.assets.length + 1;
    const assetSuffix = `-postiz-video-v${assetVersion}`;
    const defaultAssetId = `${contentId.slice(0, 128 - assetSuffix.length)}${assetSuffix}`;
    const consentRequired = Array.isArray(brief.risk_flags)
      && brief.risk_flags.includes("people_consent_and_real_assets_required");
    const actorVerified = Boolean(savedReviewer);
    return `<div class="review-block media-gate">
      <p class="eyebrow">LOKALER DATEINACHWEIS · ${escapeHtml(mediaState.approved_media_count || 0)} MEDIENZUORDNUNGEN</p>
      <h3>${replacing ? "Freigegebenes Video kontrolliert ersetzen" : "Benannte Person ordnet das freigegebene Video zu"}</h3>
      <div class="notice ${replacing ? "notice-warn" : "notice-bad"}"><strong>${replacing ? "Nachvollziehbare Ersetzung" : "Postiz-Übergabe gesperrt"}</strong><br>${replacing ? "Das bisher freigegebene Medium bleibt im Verlauf erhalten und wird erst nach einer neuen persönlichen Zuordnung abgelöst." : "Für diesen Instagram-Inhalt fehlt noch die dokumentierte Zuordnung einer freigegebenen Videodatei."}</div>
      <ol class="media-steps">
        <li>Die final freigegebene Videodatei in der Postiz-Medienbibliothek hochladen.</li>
        <li>Name und Link des Medieneintrags aus der Postiz-Medienbibliothek übernehmen.</li>
        <li>Die von Ihnen freigegebene lokale Originaldatei unten auswählen. Die Datei bleibt auf diesem Gerät.</li>
      </ol>
      <p class="media-scope-note"><strong>Prüfumfang:</strong> Die angemeldete Person bestätigt, welches bereits freigegebene Video zu diesem Inhalt gehört. Das Video selbst bleibt in der Postiz-Medienbibliothek.</p>
      ${actorVerified ? "" : `<div class="notice notice-bad"><strong>Geschützte Anmeldung erforderlich</strong><br>Der Nachweis kann erst registriert werden, wenn eine benannte Person durch den Zugangsproxy bestätigt ist.</div>`}
      <form id="postizMediaForm" class="media-evidence-form">
        <input type="hidden" id="mediaSupersedesAssetId" value="${escapeHtml(supersedesAssetId)}">
        <input type="hidden" id="mediaAssetId" value="${escapeHtml(defaultAssetId)}">
        <input type="hidden" id="mediaSha256">
        <label>Name des Medieneintrags in Postiz<input type="text" id="postizMediaId" required maxlength="256" placeholder="Name aus der Postiz-Medienbibliothek"></label>
        <label>Link zum freigegebenen Medium<input type="url" id="postizMediaPath" required maxlength="2000" placeholder="https://…/freigegebenes-medium"></label>
        <label>Freigegebene Originaldatei auswählen <span>bleibt auf diesem Gerät</span><input type="file" id="mediaOriginalFile" required accept="video/*,.mp4,.mov,.webm"></label>
        <p class="file-proof" id="mediaFileProof" role="status">Noch keine lokale Originaldatei zugeordnet.</p>
        <div class="media-form-grid">
          <label>Geprüft von<input type="text" id="mediaReviewer" autocomplete="name" required readonly aria-describedby="sessionIdentity" maxlength="200" value="${escapeHtml(savedReviewer)}" placeholder="Aus der geschützten Anmeldung"></label>
          <label>Freigegeben am<input type="datetime-local" id="mediaApprovedAt" required value="${localDateTimeValue(new Date())}"></label>
        </div>
        <label>Freigabebeleg<input type="text" id="mediaSourceRef" required maxlength="1000" placeholder="z. B. Kampagnenfreigabe vom 13.07.2026"></label>
        <label>Geprüfte Vorschau <span>Link oder Ablagereferenz</span><input type="text" id="mediaPreviewRef" required maxlength="1000" placeholder="Wo wurde genau diese Vorschau geprüft?"></label>
        <label>Einwilligungsnachweise <span>${consentRequired ? "Pflicht für sichtbare Personen" : "falls Personen erkennbar sind"}</span><textarea id="mediaConsentRefs" rows="2" ${consentRequired ? "required" : ""} placeholder="Eine Referenz pro Zeile, z. B. Consent-2026-017"></textarea></label>
        <fieldset class="media-checks"><legend>Pflichtprüfungen für genau diese Videoversion</legend><label><input type="checkbox" id="mediaBrandCheck" required><span>Markenbild, Format und visuelle Qualität geprüft</span></label><label><input type="checkbox" id="mediaFactCheck" required><span>Sichtbare Aussagen, Zahlen und Produktdarstellungen geprüft</span></label><label><input type="checkbox" id="mediaPrivacyCheck" required><span>Datenschutz, Rechte und Einwilligungen geprüft</span></label><label><input type="checkbox" id="mediaDisclosureCheck" required><span>Erforderliche KI-Kennzeichnung geprüft</span></label></fieldset>
        <div class="media-fixed-proof"><span class="signal signal-ok"></span><span>Benannte Person bestätigt die Zuordnung zum freigegebenen Video</span></div>
        <button class="button button-dark" type="submit" id="mediaSubmit" data-file-ready="false" data-idle-label="${replacing ? "Ersatzvideo zuordnen" : "Dateizuordnung dokumentieren"}" disabled>${replacing ? "Ersatzvideo zuordnen" : "Dateizuordnung dokumentieren"}</button>
        <div id="mediaFormResult" class="inline-result" role="status" aria-live="polite">Noch keine Dateizuordnung dokumentiert.</div>
      </form>
    </div>`;
  }

  async function registerPostizMedia(event) {
    event.preventDefault();
    const actor = requireAuthenticatedActor("Medienfreigabe");
    if (!actor) return;
    const form = $("postizMediaForm");
    if (!form.reportValidity()) return;
    if (!/^[a-f0-9]{64}$/i.test($("mediaSha256").value.trim())) {
      showToast("Bitte zuerst genau die freigegebene Originaldatei auswählen und prüfen lassen.");
      return;
    }
    const approvedAt = new Date($("mediaApprovedAt").value);
    if (Number.isNaN(approvedAt.getTime())) {
      showToast("Bitte einen gültigen Freigabezeitpunkt eintragen.");
      return;
    }
    if (approvedAt.getTime() > Date.now() + 5 * 60000) {
      showToast("Der Freigabezeitpunkt darf nicht in der Zukunft liegen.");
      return;
    }
    const consentRefs = $("mediaConsentRefs").value
      .split(/[\n,;]+/)
      .map((item) => item.trim())
      .filter(Boolean);
    const payload = {
      content_id: state.selectedReviewId,
      asset_id: $("mediaAssetId").value.trim(),
      media_type: "video",
      postiz_media_id: $("postizMediaId").value.trim(),
      postiz_path: $("postizMediaPath").value.trim(),
      sha256: $("mediaSha256").value.trim().toLowerCase(),
      reviewer: actor,
      approved_at: approvedAt.toISOString(),
      source_ref: $("mediaSourceRef").value.trim(),
      preview_ref: $("mediaPreviewRef").value.trim(),
      verification_method: "operator_postiz_ui",
      consent_refs: consentRefs,
      brand_check_passed: $("mediaBrandCheck").checked,
      fact_check_passed: $("mediaFactCheck").checked,
      privacy_check_passed: $("mediaPrivacyCheck").checked,
      ai_disclosure_check_passed: $("mediaDisclosureCheck").checked,
      supersedes_asset_id: $("mediaSupersedesAssetId")?.value.trim() || "",
    };
    const button = $("mediaSubmit");
    const idleLabel = button.dataset.idleLabel || "Dateizuordnung dokumentieren";
    button.disabled = true;
    button.textContent = "Nachweis wird geprüft …";
    let response;
    try {
      response = await post("/workflows/content-media-asset", payload);
    } catch (error) {
      $("mediaFormResult").className = "inline-result is-bad";
      $("mediaFormResult").innerHTML = `<strong>Nicht registriert</strong><span>${escapeHtml(businessErrorMessage(error))}</span>`;
      handleError(error);
      button.disabled = false;
      button.textContent = idleLabel;
      return;
    }
    const confirmed = response.status === "approved"
      && response.asset?.asset_id === payload.asset_id
      && response.asset?.postiz_media_id === payload.postiz_media_id
      && response.asset?.sha256 === payload.sha256
      && hasExactProviderMediaProof(response.asset)
      && response.asset?.checksum_scope === "approved_local_artifact_and_exact_postiz_path"
      && response.asset?.preview_ref === payload.preview_ref
      && response.asset?.brand_check_passed === true
      && response.asset?.fact_check_passed === true
      && response.asset?.privacy_check_passed === true
      && response.asset?.ai_disclosure_check_passed === true
      && String(response.asset?.supersedes_asset_id || "") === payload.supersedes_asset_id;
    if (!confirmed) {
      $("mediaFormResult").className = "inline-result is-warn";
      $("mediaFormResult").innerHTML = `<strong>Antwort ohne vollständige Bestätigung</strong><span>Nicht erneut registrieren. Zuerst den gespeicherten Inhaltsstatus prüfen.</span>`;
      button.disabled = false;
      button.textContent = idleLabel;
      return;
    }
    const summary = state.recent.find((item) => item.content_id === state.selectedReviewId);
    if (summary) {
      summary.postiz_media_ready = true;
      summary.approved_media_count = Number(summary.approved_media_count || 0) + (response.idempotent || payload.supersedes_asset_id ? 0 : 1);
    }
    $("mediaFormResult").className = "inline-result is-ok";
    $("mediaFormResult").innerHTML = `<strong>${response.idempotent ? "Bereits identisch dokumentiert" : "Dateizuordnung dokumentiert"}</strong><span>Die persönliche Zuordnung, Pflichtprüfungen und Freigabezeit wurden gespeichert.</span>`;
    showToast("Dateizuordnung dokumentiert – die Postiz-Übergabe wird neu geprüft.");
    try {
      await refreshApprovals();
    } catch (error) {
      console.warn("Der Mediennachweis wurde gespeichert; die Ansicht konnte nicht vollständig aktualisiert werden.");
      showToast("Video-Nachweis gespeichert; Ansicht bitte neu laden.");
    }
    if (button.isConnected) {
      button.disabled = false;
      button.textContent = idleLabel;
      applyBusinessReadiness();
    }
  }

  const frozenMediaRouteStatuses = new Set([
    "sending",
    "sent",
    "delivery_unknown",
    "confirmed",
    "reconciled",
    "reconciled_failed",
  ]);

  function mediaAssetsFrozen(contentId) {
    return state.outbox.some((route) => route.kind === "scheduler_draft"
      && route.target === "postiz"
      && route.source_id === contentId
      && !route.dry_run
      && frozenMediaRouteStatuses.has(route.status));
  }

  function trustedMediaHref(value) {
    try {
      const url = new URL(String(value || "").trim());
      if (!["http:", "https:"].includes(url.protocol) || url.username || url.password || !url.hostname) return "";
      return url.href;
    } catch (_error) {
      return "";
    }
  }

  function mediaAssetSummaryMarkup(brief, mediaState, savedReviewer) {
    const contentId = brief.id || state.selectedReviewId;
    const activeAssets = Array.isArray(mediaState?.active_assets) ? mediaState.active_assets : [];
    if (!activeAssets.length) return "";
    const frozen = mediaAssetsFrozen(contentId);
    const actorVerified = Boolean(savedReviewer);
    const activeVideo = activeAssets.find((asset) => asset.media_type === "video") || null;
    const verifiedCount = activeAssets.filter(hasExactProviderMediaProof).length;
    const allProviderVerified = verifiedCount === activeAssets.length;
    const cards = activeAssets.map((asset) => {
      const mediaUrl = trustedMediaHref(asset.postiz_path);
      const providerVerified = hasExactProviderMediaProof(asset);
      return `<article class="media-asset-card">
        <div class="media-asset-heading"><div><span class="status-tag ${providerVerified ? "ok" : "warn"}">${providerVerified ? "Bei Postiz exakt bestätigt" : "Anbieterprüfung fehlt"}</span><strong>${escapeHtml(providerVerified ? (asset.media_type === "video" ? "Bestätigtes Video" : "Bestätigtes Bild") : (asset.media_type === "video" ? "Video noch nicht bereit" : "Bild noch nicht bereit"))}</strong></div><span>${escapeHtml(asset.media_type === "video" ? "Video" : "Bild")}</span></div>
        <dl>
          <div><dt>Geprüft von</dt><dd>${escapeHtml(asset.reviewer || "–")} · ${formatDateTime(asset.approved_at)}</dd></div>
          <div><dt>Lokale Originaldatei</dt><dd>${asset.sha256 ? "Durch die benannte Person zugeordnet" : "Zuordnung fehlt"}</dd></div>
          <div><dt>Anbieterabgleich</dt><dd>${providerVerified ? "Exakte Datei und exakter Postiz-Link bestätigt" : "Nicht bestätigt – für die Übergabe gesperrt"}</dd></div>
          <div><dt>Postiz-Medium</dt><dd>${mediaUrl ? `<a href="${escapeHtml(mediaUrl)}" target="_blank" rel="noopener noreferrer">Medieneintrag öffnen ↗</a>` : "Kein gültiger Link hinterlegt"}</dd></div>
        </dl>
        ${providerVerified ? "" : `<div class="notice notice-bad"><strong>Noch nicht übergabebereit</strong><br>Ordnen Sie die lokal freigegebene Originaldatei erneut zu. Erst der exakte Anbieterabgleich bestätigt dieses Medium.</div>`}
        ${frozen ? `<div class="notice notice-warn"><strong>Nach Live-Übergabe eingefroren</strong><br>Ersetzen oder widerrufen ist nicht mehr möglich. Gleichen Sie stattdessen den Status mit Postiz ab.</div>` : !actorVerified ? `<div class="notice notice-bad"><strong>Geschützte Anmeldung erforderlich</strong><br>Nur eine bestätigte, benannte Person darf dieses Medium ersetzen oder widerrufen.</div>` : `<div class="media-asset-actions">
          ${asset.media_type === "video" ? `<button class="button button-quiet" type="button" data-replace-media="${escapeHtml(asset.asset_id)}">Video ersetzen</button>` : ""}
          <button class="text-button danger-text" type="button" data-show-media-revoke="${escapeHtml(asset.asset_id)}">Freigabe widerrufen</button>
        </div>
        <form class="media-revoke-form" data-media-revoke-form="${escapeHtml(asset.asset_id)}" hidden>
          <p><strong>Widerruf wird dauerhaft protokolliert.</strong> Das Medium kann danach nicht für eine Übergabe verwendet werden.</p>
          <div class="media-form-grid"><label>Widerrufen von<input name="reviewer" type="text" autocomplete="name" required readonly aria-describedby="sessionIdentity" maxlength="200" value="${escapeHtml(savedReviewer)}"></label><label>Widerrufen am<input name="revoked_at" type="datetime-local" required value="${localDateTimeValue(new Date())}"></label></div>
          <label>Konkreter Grund<textarea name="reason" rows="2" required maxlength="1000" placeholder="Warum darf dieses Medium nicht mehr verwendet werden?"></textarea></label>
          <div class="media-asset-actions"><button class="button button-dark" type="submit">Widerruf protokollieren</button><button class="text-button" type="button" data-cancel-media-revoke>Abbrechen</button></div>
          <div class="inline-result" data-media-action-result="${escapeHtml(asset.asset_id)}" aria-live="polite">Noch nicht widerrufen.</div>
        </form>`}
      </article>`;
    }).join("");
    return `<div class="media-assets-summary">
      <div class="media-assets-title"><div><p class="eyebrow">MEDIENZUORDNUNG</p><h4>${verifiedCount} von ${activeAssets.length} bei Postiz exakt bestätigt</h4></div><span class="signal ${allProviderVerified ? "signal-ok" : "signal-bad"}"></span></div>
      ${cards}
      ${!frozen && actorVerified && activeVideo ? `<div id="mediaReplacementPanel" class="media-replacement-panel" hidden><button class="text-button" type="button" data-cancel-media-replacement>Ersetzung schließen</button>${mediaRegistrationMarkup(brief, mediaState, savedReviewer, { supersedesAssetId: activeVideo.asset_id })}</div>` : ""}
    </div>`;
  }

  async function revokePostizMedia(event) {
    event.preventDefault();
    const actor = requireAuthenticatedActor("Medienwiderruf");
    if (!actor) return;
    const form = event.currentTarget;
    if (!form.reportValidity()) return;
    const revokedAt = new Date(form.elements.revoked_at.value);
    if (Number.isNaN(revokedAt.getTime()) || revokedAt.getTime() > Date.now() + 5 * 60000) {
      showToast("Bitte einen gültigen Widerrufszeitpunkt eintragen, der nicht in der Zukunft liegt.");
      return;
    }
    const payload = {
      content_id: state.selectedReviewId,
      asset_id: form.dataset.mediaRevokeForm,
      reviewer: actor,
      reason: form.elements.reason.value.trim(),
      revoked_at: revokedAt.toISOString(),
    };
    const button = form.querySelector('button[type="submit"]');
    const resultTarget = form.querySelector("[data-media-action-result]");
    button.disabled = true;
    button.textContent = "Widerruf wird geprüft …";
    try {
      const response = await post("/workflows/content-media-asset/revoke", payload);
      const confirmed = response.status === "revoked"
        && response.asset?.asset_id === payload.asset_id
        && response.asset?.status === "revoked";
      if (!confirmed) {
        resultTarget.className = "inline-result is-warn";
        resultTarget.innerHTML = `<strong>Antwort ohne Widerrufsbestätigung</strong><span>Nicht erneut senden; zuerst den gespeicherten Inhaltsstatus prüfen.</span>`;
        return;
      }
      resultTarget.className = "inline-result is-ok";
      resultTarget.innerHTML = `<strong>${response.idempotent ? "Widerruf bereits identisch protokolliert" : "Freigabe widerrufen"}</strong><span>Das Medium ist nicht mehr für Postiz freigegeben.</span>`;
      showToast("Medienfreigabe widerrufen; Übergabestatus wird neu geprüft.");
      await refreshApprovals();
    } catch (error) {
      resultTarget.className = "inline-result is-bad";
      resultTarget.innerHTML = `<strong>Nicht widerrufen</strong><span>${escapeHtml(businessErrorMessage(error))}</span>`;
      handleError(error);
    } finally {
      if (button.isConnected) {
        button.disabled = false;
        button.textContent = "Widerruf protokollieren";
      }
    }
  }

  function bindMediaAssetActions() {
    document.querySelectorAll("[data-replace-media]").forEach((button) => button.addEventListener("click", () => {
      const panel = $("mediaReplacementPanel");
      if (!panel) return;
      panel.hidden = false;
      panel.scrollIntoView({ behavior: "smooth", block: "start" });
      $("postizMediaId")?.focus({ preventScroll: true });
    }));
    document.querySelector("[data-cancel-media-replacement]")?.addEventListener("click", () => {
      const panel = $("mediaReplacementPanel");
      if (panel) panel.hidden = true;
    });
    document.querySelectorAll("[data-show-media-revoke]").forEach((button) => button.addEventListener("click", () => {
      const form = document.querySelector(`[data-media-revoke-form="${CSS.escape(button.dataset.showMediaRevoke)}"]`);
      if (form) form.hidden = false;
    }));
    document.querySelectorAll("[data-cancel-media-revoke]").forEach((button) => button.addEventListener("click", () => {
      const form = button.closest(".media-revoke-form");
      if (form) form.hidden = true;
    }));
    document.querySelectorAll(".media-revoke-form").forEach((form) => form.addEventListener("submit", revokePostizMedia));
  }

  function schedulerHandoffMarkup(brief, mediaState, savedReviewer) {
    const readiness = postizWriteReadiness();
    const latest = latestSchedulerHandoff(brief.id || state.selectedReviewId);
    const auditAvailable = state.outboxAvailable;
    const attempted = mediaAssetsFrozen(brief.id || state.selectedReviewId);
    const canReconcile = latest && ["sent", "delivery_unknown", "confirmed"].includes(latest.status) && !latest.dry_run;
    const videoRequired = isInstagramReel(brief);
    const videoReady = mediaState?.postiz_media_ready === true;
    const actorVerified = Boolean(savedReviewer);
    if (videoRequired && !videoReady && !attempted) {
      const activeAssets = Array.isArray(mediaState?.active_assets) ? mediaState.active_assets : [];
      const activeVideo = activeAssets.find((asset) => asset.media_type === "video") || null;
      if (activeVideo) return mediaAssetSummaryMarkup(brief, mediaState, savedReviewer);
      const existingAssignments = mediaAssetSummaryMarkup(brief, mediaState, savedReviewer);
      return `${existingAssignments}${mediaRegistrationMarkup(brief, mediaState || {}, savedReviewer)}`;
    }
    const modeCopy = readiness.live
      ? "Externe Übergabe ist laut Server ausdrücklich freigegeben. Mit Ihrer Bestätigung wird nur ein Entwurf in Postiz angelegt – niemals veröffentlicht."
      : "Vorschau: Noch nichts gesendet. Die Übergabe bleibt gesperrt, bis alle Verbindungen freigegeben sind.";
    return `<div class="review-block handoff-action">
      <p class="eyebrow">GEREGELTE ÜBERGABE</p>
      <h3>Postiz-Entwurf</h3>
      <p>${escapeHtml(modeCopy)}</p>
      ${videoRequired ? `<div class="media-ready-summary ${videoReady ? "is-ready" : "is-missing"}"><span class="signal ${videoReady ? "signal-ok" : "signal-bad"}"></span><div><strong>${videoReady ? "Exakt bestätigtes Postiz-Video vorhanden" : "Exakt bestätigtes Postiz-Video fehlt"}</strong><small>${escapeHtml(mediaState?.provider_verified_media_count || 0)} von ${escapeHtml(mediaState?.approved_media_count || 0)} Medien bei Postiz exakt bestätigt</small></div></div>` : ""}
      ${mediaAssetSummaryMarkup(brief, mediaState, savedReviewer)}
      <div class="handoff-mode ${readiness.live ? "is-live" : "is-dry"}"><span class="signal ${readiness.live ? "signal-ok" : "signal-warn"}"></span><strong>${readiness.live ? "Entwurfsübergabe bereit" : "Nur Vorschau · noch nichts gesendet"}</strong></div>
      ${actorVerified ? "" : `<div class="notice notice-bad"><strong>Geschützte Anmeldung erforderlich</strong><br>Eine Übergabe oder ein Anbieterabgleich kann erst durch eine bestätigte, benannte Person ausgelöst werden.</div>`}
      ${!auditAvailable
        ? `<div class="notice notice-bad">Das Übergabeprotokoll ist nicht erreichbar. Deshalb wird keine neue Übergabe angeboten, bis ein sicherer Doppelversand ausgeschlossen ist.</div>`
        : attempted
        ? `<div class="notice ${latest.status === "delivery_unknown" ? "notice-bad" : "notice-ok"}">${latest.status === "delivery_unknown" ? "Kein erneutes Senden möglich: Zuerst den Status mit Postiz abgleichen." : "Die Übergabe wurde bereits ausgelöst. Ein erneutes Senden wird nicht angeboten."}</div>`
        : `<form id="schedulerHandoffForm">${readiness.live ? `<label class="handoff-confirm"><input type="checkbox" id="confirmPostizHandoff" required><span>Ich bestätige die Übergabe dieses freigegebenen Inhalts als Entwurf an Postiz.</span></label>` : ""}<button class="button button-primary" type="submit" id="routeSchedulerDraft" ${actorVerified ? "" : "disabled"}>In Postiz als Entwurf übergeben</button></form>`}
      ${canReconcile ? `<button class="button button-dark" type="button" data-reconcile-postiz="${escapeHtml(latest.id)}" ${actorVerified ? "" : "disabled"}>Status mit Postiz abgleichen</button>` : ""}
      <div id="handoffResult" aria-live="polite">${handoffSummaryMarkup(latest)}</div>
      <div data-reconciliation-result="${escapeHtml(latest?.id || "")}">${reconciliationConfirmationMarkup(latest?.id || "")}</div>
    </div>`;
  }

  function reviewQueueItemMarkup(item) {
    const instagramReel = isInstagramReel(item);
    const mediaReady = item.postiz_media_ready === true;
    const readyCopy = item.status !== "ready_to_schedule"
      ? ""
      : instagramReel && !mediaReady
        ? `<em class="media-needed">Video fehlt · Übergabe gesperrt</em>`
        : instagramReel
          ? `<em>Video bestätigt · Postiz-Übergabe möglich</em>`
          : `<em>Postiz-Übergabe möglich</em>`;
    return `<button class="queue-item ${state.selectedReviewId === item.content_id ? "is-selected" : ""}" type="button" data-review-id="${escapeHtml(item.content_id)}" data-campaign-id="${escapeHtml(item.campaign_id || "")}" data-channel="${escapeHtml(item.channel || "")}" data-format="${escapeHtml(item.format || "")}" data-media-ready="${instagramReel ? String(mediaReady) : "not-required"}" aria-pressed="${state.selectedReviewId === item.content_id}"><span class="status-tag ${statusClass(item.status)}">${escapeHtml(friendlyStatus(item.status))}</span><strong>${escapeHtml(item.campaign || "Kampagneninhalt")}</strong><small>${escapeHtml(friendlyFormat(item.format))} · ${formatDate(item.updated_at)}</small>${readyCopy}</button>`;
  }

  async function refreshApprovals() {
    const [data, outbox, phases] = await Promise.all([
      request("/workflows/states?limit=100").catch(() => ({ items: [], unavailable: true })),
      request("/workflows/outbox?limit=100").catch(() => ({ items: [], unavailable: true })),
      request("/workflows/phase-status").catch(() => null),
    ]);
    state.approvalDataAvailable = data.unavailable !== true;
    state.recentAvailable = state.approvalDataAvailable;
    if (state.approvalDataAvailable) state.recent = data.items || [];
    state.outbox = outbox.items || [];
    state.outboxAvailable = outbox.unavailable !== true;
    state.approvalReadinessVerified = Boolean(phases);
    if (phases) {
      state.phases = phases;
      state.integrations = phases.integrations || state.integrations;
    }
    if (!state.approvalDataAvailable) {
      $("reviewCount").textContent = "–";
      $("navReviewCount").textContent = "–";
      $("reviewQueue").innerHTML = `<div class="notice notice-warn">Offene Freigaben und Planungsaufgaben konnten nicht geladen werden. Der Umfang ist unbekannt; es wird kein Nullstand angezeigt.</div>`;
      $("reviewDetail").innerHTML = `<div class="empty-state"><span>!</span><h3>Arbeitsstand unbekannt</h3><p>Bitte aktualisieren Sie die Seite, bevor Sie eine Freigabe- oder Planungsentscheidung treffen.</p></div>`;
      return;
    }
    const currentItems = currentContentVersions(state.recent);
    const reviewQueue = reviewAttentionItems(currentItems);
    const handoffQueue = currentItems.filter((item) => item.status === "ready_to_schedule");
    const queue = [...reviewQueue, ...handoffQueue];
    $("reviewCount").textContent = String(queue.length);
    $("navReviewCount").textContent = String(queue.length);
    $("reviewQueue").innerHTML = queue.length ? queue.map(reviewQueueItemMarkup).join("") : `<div class="empty-state" style="min-height:260px"><p>Keine echten Entwürfe oder Übergaben warten.</p></div>`;
    document.querySelectorAll("[data-review-id]").forEach((button) => button.addEventListener("click", () => loadReview(button.dataset.reviewId).catch(handleError)));
    if (state.selectedReviewId && queue.some((item) => item.content_id === state.selectedReviewId)) await loadReview(state.selectedReviewId);
    else if (state.selectedReviewId) {
      state.selectedReviewId = "";
      $("reviewDetail").innerHTML = `<div class="empty-state"><span>✓</span><h3>Kein offener Schritt mehr</h3><p>Der Inhalt ist in die nächste Phase gewechselt. Details finden Sie unter Ergebnisse.</p></div>`;
    }
  }

  async function loadReview(contentId) {
    state.selectedReviewId = contentId;
    let payload;
    try {
      payload = await request(`/workflows/states/${encodeURIComponent(contentId)}`);
    } catch (error) {
      $("reviewDetail").innerHTML = `<div class="empty-state"><span>!</span><h3>Entwurfsstatus unbekannt</h3><p>Der Inhalt konnte nicht sicher geladen werden. Es ist keine Freigabeentscheidung möglich.</p></div>`;
      throw error;
    }
    const brief = payload.brief || {};
    const mediaState = mediaStateFor(contentId, payload);
    const concept = brief.reel_concept || {};
    const citations = citationsOf(brief).length ? citationsOf(brief) : citationsOf(concept);
    const internalEvidence = Array.isArray(payload.evidence_records) ? payload.evidence_records : [];
    const evidenceInspectable = reviewEvidenceInspectable(citations, internalEvidence);
    const generation = brief.generation || payload.generation || {};
    const approvedPrimaryGeneration = generation.status === "ai_generated" && generation.fallback_used === false;
    const generationLabel = approvedPrimaryGeneration
      ? "Mit lokaler KI erstellt und automatisch auf Struktur geprüft."
      : generation.status === "ai_generated"
        ? "Dieser Entwurf wurde nicht mit dem freigegebenen Standard erstellt. Bitte neu erstellen, bevor er gepr\u00fcft wird."
      : generation.status === "deterministic_fallback"
        ? "Nur sichere Arbeitsvorlage – nicht mit KI erstellt und nicht freigabefähig."
        : "Kein verlässlicher Erstellungsnachweis – vor der Freigabe neu erstellen.";
    const generationReady = approvedPrimaryGeneration;
    const savedReviewer = authenticatedActor();
    const actorVerified = Boolean(savedReviewer);
    const workflowErrors = Array.isArray(payload.errors) ? payload.errors.filter(Boolean) : [];
    const riskFlags = Array.isArray(brief.risk_flags) ? brief.risk_flags.filter(Boolean) : [];
    const errorMarkup = workflowErrors.length
      ? `<div class="notice notice-bad"><strong>Warum dieser Entwurf nicht weiter kann</strong><ul>${[...new Set(workflowErrors.map(friendlyWorkflowError))].map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></div>`
      : "";
    const riskMarkup = riskFlags.length
      ? `<div class="notice notice-warn"><strong>Vor Freigabe klären</strong><ul>${riskFlags.map((item) => `<li>${escapeHtml(friendlyRisk(item))}</li>`).join("")}</ul></div>`
      : "";
    const peopleEvidenceRequired = riskFlags.includes("people_consent_and_real_assets_required");
    const activePeopleVideo = mediaState.verified_active_assets.find((asset) => asset.media_type === "video") || null;
    const peopleEvidenceReady = Boolean(
      activePeopleVideo
      && Array.isArray(activePeopleVideo.consent_refs)
      && activePeopleVideo.consent_refs.some((item) => String(item || "").trim()),
    );
    const peopleEvidenceMarkup = peopleEvidenceRequired && brief.status === "needs_human_review"
      ? activePeopleVideo
        ? `${mediaAssetSummaryMarkup(brief, mediaState, savedReviewer)}${peopleEvidenceReady ? `<div class="notice notice-ok"><strong>Personen- und Mediennachweis vollständig</strong><br>Die menschliche Inhaltsfreigabe kann jetzt bewusst durchgeführt werden.</div>` : `<div class="notice notice-bad"><strong>Einwilligungsnachweise fehlen</strong><br>Ersetzen Sie das Video kontrolliert durch eine Version mit vollständigen Einwilligungsreferenzen.</div>`}`
        : mediaRegistrationMarkup(brief, mediaState, savedReviewer)
      : "";
    const approvalPrerequisitesReady = actorVerified
      && generationReady
      && evidenceInspectable
      && (!peopleEvidenceRequired || peopleEvidenceReady);
    const approvalEnabled = approvalPrerequisitesReady && capabilityCanRun("approval");
    const reviewActionMarkup = brief.status === "needs_human_review"
      ? `${peopleEvidenceMarkup}<form class="review-block" id="approvalForm"><h3>Pflichtprüfungen</h3>${actorVerified ? "" : `<div class="notice notice-bad">Geschützte Anmeldung erforderlich, bevor eine Freigabe protokolliert werden kann.</div>`}${generationReady ? "" : `<div class="notice notice-bad"><strong>Freigabe gesperrt</strong><br>Bitte mit lokaler KI neu erstellen, bevor eine Freigabe möglich ist.</div>`}${evidenceInspectable ? "" : `<div class="notice notice-bad"><strong>Faktenprüfung nicht möglich</strong><br>Es fehlt eine anklickbare öffentliche Quelle oder ein vollständig bestätigter interner Beleg. Die Faktenbestätigung bleibt gesperrt.</div>`}${peopleEvidenceRequired && !peopleEvidenceReady ? `<div class="notice notice-bad"><strong>Freigabe noch gesperrt</strong><br>Registrieren Sie zuerst das echte Video und die Einwilligungsnachweise aller sichtbaren Personen.</div>` : ""}<label class="creator-note">Prüfer/in<input type="text" id="reviewerName" autocomplete="name" required readonly aria-describedby="sessionIdentity" value="${escapeHtml(savedReviewer)}" placeholder="Aus der geschützten Anmeldung"></label><label class="creator-note">Markenfit · 0–100<input type="number" id="brandScore" min="0" max="100" step="1" required placeholder="Wert bewusst eintragen"></label><div class="check-list"><label class="${evidenceInspectable ? "" : "is-disabled"}"><input type="checkbox" id="factCheck" ${evidenceInspectable ? "" : "disabled"}> <span>Fakten und Quellen geprüft</span></label><label><input type="checkbox" id="privacyCheck"> <span>Datenschutz und Einwilligungen geprüft</span></label><label><input type="checkbox" id="disclosureCheck"> <span>KI-Kennzeichnung geprüft</span></label></div><label class="creator-note" style="margin-top:12px">Notiz<textarea id="approvalNotes" rows="3" placeholder="Warum wird freigegeben oder überarbeitet?"></textarea></label><div class="review-actions"><button class="button button-quiet" type="button" id="requestRevision" ${actorVerified && capabilityCanRun("approval") ? "" : "disabled"}>Überarbeiten</button><button class="button button-primary" type="submit" data-approval-prerequisites="${approvalPrerequisitesReady}" ${approvalEnabled ? "" : "disabled"}>Freigeben</button></div></form>`
      : brief.status === "ready_to_schedule"
        ? schedulerHandoffMarkup(brief, mediaState, savedReviewer)
      : ["revision_requested", "blocked"].includes(brief.status)
        ? `<form class="review-block" id="revisionForm"><h3>Neue Version erstellen</h3><p>Der alte Entwurf und seine Prüfung bleiben unverändert im Prüfverlauf.</p>${actorVerified ? "" : `<div class="notice notice-bad">Geschützte Anmeldung erforderlich, bevor eine neue Version erstellt werden kann.</div>`}<label class="creator-note">Bearbeiter/in<input type="text" id="revisionEditor" autocomplete="name" required readonly aria-describedby="sessionIdentity" value="${escapeHtml(savedReviewer)}" placeholder="Aus der geschützten Anmeldung"></label><label class="creator-note">Was soll sich ändern?<textarea id="revisionNotes" rows="4" placeholder="Konkrete Korrekturen für Einstieg, Aussage, Ton oder Handlungsaufforderung"></textarea></label><button class="button button-primary" type="submit" ${actorVerified ? "" : "disabled"}>Neue Version mit lokaler KI erstellen</button></form>`
        : `<div class="review-block"><h3>Nächster Schritt</h3><p>Dieser Status kann nicht freigegeben werden. Beheben Sie zuerst die oben genannten Blocker oder starten Sie eine neue, belegte Recherche.</p></div>`;
    $("reviewDetail").innerHTML = `<div class="review-document">
      <div class="content-preview"><span class="status-tag ${statusClass(brief.status)}">${escapeHtml(friendlyStatus(brief.status))}</span><h3>${escapeHtml(brief.campaign || "Content-Entwurf")}</h3><p class="page-subtitle">${escapeHtml(brief.channel || "")} · ${escapeHtml(friendlyFormat(brief.format))}</p><pre>${escapeHtml(brief.public_copy || brief.draft || "Noch kein Inhalt erzeugt.")}</pre>${productionPlanMarkup(brief)}</div>
      <aside class="review-sidebar">
        ${errorMarkup}
        ${riskMarkup}
        <div class="review-block"><h3>Entstehung</h3><p>${escapeHtml(generationLabel)}</p></div>
        <div class="review-block"><h3>Quellen & Belege</h3>${citationMarkup(citations)}${internalEvidenceMarkup(internalEvidence)}</div>
        ${reviewActionMarkup}
      </aside>
    </div>`;
    if ($("brandScore")) {
      $("brandScore").placeholder = "90–100 = freigabefähig";
      $("brandScore").insertAdjacentHTML(
        "afterend",
        '<small class="field-guidance">90–100: markengerecht · 70–89: überarbeiten · unter 70: stoppen</small>',
      );
    }
    document.querySelectorAll("[data-review-id]").forEach((button) => {
      const selected = button.dataset.reviewId === contentId;
      button.classList.toggle("is-selected", selected);
      button.setAttribute("aria-pressed", String(selected));
    });
    $("approvalNotes")?.setAttribute("required", "required");
    $("approvalForm")?.addEventListener("submit", (event) => applyApproval(event, "approved"));
    $("requestRevision")?.addEventListener("click", (event) => applyApproval(event, "major_revision"));
    $("revisionForm")?.addEventListener("submit", createRevision);
    $("schedulerHandoffForm")?.addEventListener("submit", submitSchedulerHandoff);
    $("postizMediaForm")?.addEventListener("submit", registerPostizMedia);
    $("mediaOriginalFile")?.addEventListener("change", () => verifySelectedFile({
      fileId: "mediaOriginalFile",
      shaId: "mediaSha256",
      proofId: "mediaFileProof",
      submitId: "mediaSubmit",
    }));
    bindMediaAssetActions();
    bindPostizReconciliationActions();
    applyBusinessReadiness();
  }

  async function submitSchedulerHandoff(event) {
    event.preventDefault();
    if (!requireAuthenticatedActor("Postiz-Übergabe")) return;
    const selectedSummary = state.recent.find((item) => item.content_id === state.selectedReviewId) || {};
    if (isInstagramReel(selectedSummary) && selectedSummary.postiz_media_ready !== true) {
      showToast("Übergabe gesperrt: Zuerst das freigegebene Video in Postiz hochladen und registrieren.");
      await loadReview(state.selectedReviewId).catch(() => undefined);
      return;
    }
    const readiness = postizWriteReadiness();
    if (readiness.live && !$("confirmPostizHandoff")?.checked) {
      showToast("Bitte die externe Entwurfsübergabe bewusst bestätigen.");
      return;
    }
    const button = $("routeSchedulerDraft");
    button.disabled = true;
    button.textContent = readiness.live ? "Entwurf wird übergeben …" : "Übergabe wird vorbereitet …";
    try {
      const response = await post("/workflows/route-scheduler-draft", {
        content_id: state.selectedReviewId,
        target: "postiz",
        dry_run: !readiness.live,
      });
      const route = response.route || {};
      if (route.id) state.outbox = [route, ...state.outbox.filter((item) => item.id !== route.id)];
      if ($("handoffResult")) $("handoffResult").innerHTML = handoffSummaryMarkup(route);
      if (route.status === "sent") showToast("Postiz-Entwurf übergeben – noch nicht veröffentlicht.");
      else if (route.status === "prepared") showToast("Nur vorbereitet – Postiz wurde nicht verändert.");
      else if (route.status === "delivery_unknown") showToast("Ausgang unklar – bitte in Postiz abgleichen und nicht erneut senden.");
      else showToast(handoffStatusCopy(route));
      const outbox = await request("/workflows/outbox?limit=100").catch(() => ({ items: state.outbox, unavailable: true }));
      state.outbox = outbox.items || state.outbox;
      state.outboxAvailable = outbox.unavailable !== true;
      await loadReview(state.selectedReviewId).catch(() => console.warn("Die Übergabe wurde gespeichert; die Ansicht konnte nicht vollständig aktualisiert werden."));
    } catch (error) {
      if ($("handoffResult")) $("handoffResult").innerHTML = `<div class="inline-result is-bad"><strong>Übergabe nicht bestätigt</strong><span>${escapeHtml(businessErrorMessage(error))}</span></div>`;
      handleError(error);
    } finally {
      button.disabled = false;
      button.textContent = "In Postiz als Entwurf übergeben";
    }
  }

  async function createRevision(event) {
    event.preventDefault();
    const editor = requireAuthenticatedActor("Content-Revision");
    if (!editor) return;
    const revisionNotes = $("revisionNotes")?.value.trim() || "";
    if (!editor || !revisionNotes) return showToast("Bitte Bearbeiter/in und konkrete Korrekturen eintragen.");
    try {
      const result = await post("/workflows/revise-content", {
        content_id: state.selectedReviewId,
        editor,
        revision_notes: revisionNotes,
      });
      state.selectedReviewId = result.content_id;
      showToast("Neue Version erstellt – der bisherige Prüfverlauf bleibt erhalten.");
      await refreshCore();
      await refreshApprovals();
    } catch (error) { handleError(error); }
  }

  async function applyApproval(event, decision) {
    event.preventDefault();
    const reviewer = requireAuthenticatedActor("Content-Freigabe");
    if (!reviewer) return;
    const approved = decision === "approved";
    const fact = $("factCheck")?.checked || false;
    const privacy = $("privacyCheck")?.checked || false;
    const disclosure = $("disclosureCheck")?.checked || false;
    const notes = $("approvalNotes")?.value.trim() || "";
    const brandScoreInput = $("brandScore")?.value.trim() || "";
    const brandScore = Number(brandScoreInput);
    if (!reviewer) return showToast("Bitte den Namen der prüfenden Person eintragen.");
    if (!brandScoreInput || !Number.isInteger(brandScore) || brandScore < 0 || brandScore > 100) return showToast("Bitte den Markenfit bewusst als ganze Zahl zwischen 0 und 100 bewerten.");
    if (approved && (!fact || !privacy || !disclosure)) return showToast("Bitte alle drei Pflichtprüfungen abschließen.");
    if (approved && brandScore < 90) return showToast("Unter 90 Punkten bitte Überarbeitung anfordern.");
    if (!notes) return showToast("Bitte die Freigabe- oder Überarbeitungsentscheidung begründen.");
    try {
      const result = await post("/workflows/approve-content", {
        content_id: state.selectedReviewId,
        reviewer,
        decision,
        brand_score: brandScore,
        fact_check_passed: fact,
        privacy_check_passed: privacy,
        ai_disclosure_check_passed: disclosure,
        notes,
      });
      showToast(result.state?.next_step === "scheduler" ? "Freigegeben – Scheduler-Entwurf ist bereit." : "Überarbeitung wurde angefordert.");
      await refreshCore();
      await refreshApprovals();
    } catch (error) { handleError(error); }
  }

  async function createWeeklyPlan() {
    $("createWeeklyPlan").disabled = true;
    $("createWeeklyPlan").textContent = "Plan wird erstellt …";
    try {
      const response = await post("/workflows/weekly-planning", { calendar_mode: "rolling_30_day" });
      const created = response.summary?.created_now ?? response.created_now?.length ?? response.created?.length ?? 0;
      const existing = response.summary?.already_present ?? response.already_present?.length ?? 0;
      const skipped = response.summary?.skipped_planned ?? response.skipped_planned?.length ?? 0;
      showToast(`${created} neue Wochenentwürfe erstellt${existing ? ` · ${existing} bereits vorhanden` : ""}${skipped ? ` · ${skipped} spätere Kampagnen noch nicht fällig` : ""}.`);
      await refreshCore();
    } catch (error) { handleError(error); }
    finally { $("createWeeklyPlan").textContent = "Wochenentwürfe für aktive Kampagnen erstellen"; applyBusinessReadiness(); }
  }

  function outboxRecordMarkup(item) {
    const reconciliation = item.status === "delivery_unknown";
    const canReconcile = item.kind === "scheduler_draft"
      && item.target === "postiz"
      && ["sent", "delivery_unknown", "confirmed"].includes(item.status)
      && !item.dry_run;
    const businessLabel = item.campaign
      || (item.kind === "lead" ? "Vertriebsreaktion" : contentBusinessLabel(item.source_id, "Freigegebener Kampagneninhalt"));
    return `<article class="handoff-record ${reconciliation ? "needs-reconciliation" : ""}">
      <div class="handoff-record-head"><div><span class="status-tag ${statusClass(item.status)}">${escapeHtml(friendlyStatus(item.status))}</span><strong>${escapeHtml(businessLabel)}</strong></div><span class="provider-badge">${escapeHtml(item.target === "postiz" ? "Redaktionsplanung" : item.target === "crm" ? "Vertriebsübergabe" : "Externe Übergabe")}</span></div>
      <p>${escapeHtml(handoffStatusCopy(item))}</p>
      <dl>
        <div><dt>Modus</dt><dd>${item.dry_run ? "Nur Vorbereitung" : "Externe Übergabe"}</dd></div>
        <div><dt>Begonnen</dt><dd>${formatDateTime(item.created_at)}</dd></div>
        <div><dt>Zuletzt geändert</dt><dd>${formatDateTime(item.updated_at || item.created_at)}</dd></div>
      </dl>
      ${reconciliation ? `<div class="reconciliation-alert"><strong>Abgleich erforderlich</strong><span>Nicht erneut senden. Prüfen Sie zuerst direkt in Postiz, ob bereits ein Entwurf existiert.</span></div>` : ""}
      ${canReconcile ? `<button class="button button-quiet reconcile-button" type="button" data-reconcile-postiz="${escapeHtml(item.id)}">Status mit Postiz abgleichen</button>` : ""}
      <div data-reconciliation-result="${escapeHtml(item.id || "")}">${reconciliationConfirmationMarkup(item.id || "")}</div>
    </article>`;
  }

  function setAnalyticsEntryVisible(visible) {
    const form = $("analyticsEntryForm");
    const gate = $("analyticsSelectionGate");
    if (form) form.hidden = !visible;
    if (gate) gate.hidden = visible;
    if ($("submitAnalytics")) {
      $("submitAnalytics").disabled = !visible || !authenticatedActor();
    }
  }

  function renderDueAnalytics(dueResults) {
    const unavailable = dueResults.some((item) => item.unavailable);
    const items = dueResults.flatMap((item) => item.items || []);
    $("analyticsDueCount").textContent = String(items.length);
    if (unavailable && !items.length) {
      $("analyticsDueList").innerHTML = `<div class="notice notice-warn">Fällige Auswertungen konnten gerade nicht vollständig geladen werden. Es wird nicht behauptet, dass keine Aufgaben offen sind.</div>`;
      if (!$("analyticsContentId")?.value.trim() && !state.analyticsCorrection) setAnalyticsEntryVisible(false);
      return;
    }
    $("analyticsDueList").innerHTML = items.length ? items.map((item) => {
      const label = item.campaign || contentBusinessLabel(item.content_id, "Veröffentlichter Kampagneninhalt");
      return `<article class="due-item">
        <div><span class="status-tag">${escapeHtml(reviewWindowLabel(item.review_window))}</span><strong>${escapeHtml(label)}</strong><small>Veröffentlicht: ${formatDateTime(item.published_at)} · fällig seit ${formatDateTime(item.due_at)}</small></div>
        <button class="button button-quiet" type="button" data-fill-analytics="${escapeHtml(item.content_id)}" data-content-label="${escapeHtml(label)}" data-review-window="${escapeHtml(item.review_window)}" data-published-at="${escapeHtml(item.published_at || "")}">Messwerte eintragen</button>
      </article>`;
    }).join("") : `<div class="empty-compact"><strong>Aktuell nichts fällig</strong><p>Es gibt derzeit keine vom Server bestätigte Messaufgabe.</p></div>`;
    if (!items.length && !$("analyticsContentId")?.value.trim() && !state.analyticsCorrection) {
      setAnalyticsEntryVisible(false);
    }
    if (unavailable) $("analyticsDueList").insertAdjacentHTML("beforeend", `<div class="notice notice-warn">Mindestens ein Messfenster konnte nicht geprüft werden. Die Liste kann unvollständig sein.</div>`);
    document.querySelectorAll("[data-fill-analytics]").forEach((button) => button.addEventListener("click", () => {
      prefillAnalyticsForm(button.dataset.fillAnalytics, button.dataset.reviewWindow, button.dataset.publishedAt, button.dataset.contentLabel);
    }));
  }

  function localDateTimeValue(date) {
    const shifted = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
    return shifted.toISOString().slice(0, 16);
  }

  function reviewWindowMilliseconds(reviewWindow) {
    return { "72h": 72 * 3600000, "7d": 7 * 86400000, "14d": 14 * 86400000, "30d": 30 * 86400000 }[reviewWindow] || 72 * 3600000;
  }

  function setAnalyticsTimeDefaults(reviewWindow, { force = false } = {}) {
    const now = new Date();
    const periodEnd = new Date(now.getTime());
    const periodStart = new Date(periodEnd.getTime() - reviewWindowMilliseconds(reviewWindow));
    if (force || !$("analyticsPeriodEnd").value) $("analyticsPeriodEnd").value = localDateTimeValue(periodEnd);
    if (force || !$("analyticsPeriodStart").value) $("analyticsPeriodStart").value = localDateTimeValue(periodStart);
    if (force || !$("analyticsRetrievedAt").value) $("analyticsRetrievedAt").value = localDateTimeValue(now);
    ["analyticsEvidenceEngagementRetrievedAt", "analyticsEvidenceLandingRetrievedAt", "analyticsEvidenceCrmRetrievedAt"].forEach((id) => {
      if (force || !$(id).value) $(id).value = localDateTimeValue(now);
    });
  }

  function prefillAnalyticsForm(contentId, reviewWindow, publishedAt = "", contentLabel = "") {
    $("analyticsContentId").value = contentId || "";
    $("analyticsContentLabel").value = contentLabel || contentBusinessLabel(contentId, "Veröffentlichter Kampagneninhalt");
    $("analyticsSourceRef").value = "";
    $("analyticsReviewWindow").value = reviewWindow || "72h";
    setAnalyticsTimeDefaults($("analyticsReviewWindow").value, { force: true });
    const publication = new Date(publishedAt);
    if (!Number.isNaN(publication.getTime())) $("analyticsPeriodStart").value = localDateTimeValue(publication);
    setAnalyticsEntryVisible(Boolean(contentId));
    $("analyticsEntryPanel").scrollIntoView({ behavior: "smooth", block: "start" });
    $("analyticsImpressions").focus({ preventScroll: true });
    showToast("Inhalt und Messfenster wurden übernommen.");
  }

  function analyticsNumber(id) {
    const value = $(id).value.trim();
    return value === "" ? 0 : Number(value);
  }

  function analyticsTimestamp(id) {
    const value = $(id).value;
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "" : date.toISOString();
  }

  const analyticsMetricLabels = {
    impressions: "Impressionen",
    saves: "Gespeichert",
    shares: "Geteilt",
    comments_from_target_buyers: "Käufer-Kommentare",
    profile_visits: "Profilbesuche",
    clicks: "Klicks",
    leads: "Leads",
    qualified_leads: "Qualifizierte Leads",
    booked_calls: "Gebuchte Gespräche",
    landing_page_visits: "Landingpage-Besuche",
    landing_page_conversions: "Landingpage-Abschlüsse",
    pipeline_value_eur: "Pipeline-Wert",
  };

  const analyticsMetricInputIds = {
    impressions: "analyticsImpressions",
    saves: "analyticsSaves",
    shares: "analyticsShares",
    comments_from_target_buyers: "analyticsBuyerComments",
    profile_visits: "analyticsProfileVisits",
    clicks: "analyticsClicks",
    leads: "analyticsLeads",
    qualified_leads: "analyticsQualifiedLeads",
    booked_calls: "analyticsBookedCalls",
    landing_page_visits: "analyticsLandingVisits",
    landing_page_conversions: "analyticsLandingConversions",
    pipeline_value_eur: "analyticsPipelineValue",
  };

  const analyticsEvidenceGroups = [
    {
      key: "engagement",
      label: "Interaktion & Reichweite",
      enabledId: "analyticsEvidenceEngagementEnabled",
      systemId: "analyticsEvidenceEngagementSystem",
      refId: "analyticsEvidenceEngagementRef",
      retrievedId: "analyticsEvidenceEngagementRetrievedAt",
      shaId: "analyticsEvidenceEngagementSha256",
      fileId: "analyticsEvidenceEngagementFile",
      proofId: "analyticsEvidenceEngagementProof",
      metricFields: ["impressions", "saves", "shares", "comments_from_target_buyers", "profile_visits", "clicks"],
    },
    {
      key: "landing",
      label: "Landingpage",
      enabledId: "analyticsEvidenceLandingEnabled",
      systemId: "analyticsEvidenceLandingSystem",
      refId: "analyticsEvidenceLandingRef",
      retrievedId: "analyticsEvidenceLandingRetrievedAt",
      shaId: "analyticsEvidenceLandingSha256",
      fileId: "analyticsEvidenceLandingFile",
      proofId: "analyticsEvidenceLandingProof",
      metricFields: ["landing_page_visits", "landing_page_conversions"],
    },
    {
      key: "crm",
      label: "CRM & Pipeline",
      enabledId: "analyticsEvidenceCrmEnabled",
      systemId: "analyticsEvidenceCrmSystem",
      refId: "analyticsEvidenceCrmRef",
      retrievedId: "analyticsEvidenceCrmRetrievedAt",
      shaId: "analyticsEvidenceCrmSha256",
      fileId: "analyticsEvidenceCrmFile",
      proofId: "analyticsEvidenceCrmProof",
      metricFields: ["leads", "qualified_leads", "booked_calls", "pipeline_value_eur"],
    },
  ];

  function analyticsMetrics() {
    return {
      impressions: analyticsNumber("analyticsImpressions"),
      saves: analyticsNumber("analyticsSaves"),
      shares: analyticsNumber("analyticsShares"),
      comments_from_target_buyers: analyticsNumber("analyticsBuyerComments"),
      profile_visits: analyticsNumber("analyticsProfileVisits"),
      clicks: analyticsNumber("analyticsClicks"),
      leads: analyticsNumber("analyticsLeads"),
      qualified_leads: analyticsNumber("analyticsQualifiedLeads"),
      booked_calls: analyticsNumber("analyticsBookedCalls"),
      landing_page_visits: analyticsNumber("analyticsLandingVisits"),
      landing_page_conversions: analyticsNumber("analyticsLandingConversions"),
      pipeline_value_eur: analyticsNumber("analyticsPipelineValue"),
    };
  }

  function analyticsEvidenceArtifacts() {
    return analyticsEvidenceGroups
      .filter((group) => $(group.enabledId).checked)
      .map((group) => ({
        system: $(group.systemId).value.trim(),
        ref: $(group.refId).value.trim(),
        retrieved_at: analyticsTimestamp(group.retrievedId),
        sha256: $(group.shaId).value.trim().toLowerCase(),
        metric_fields: [...group.metricFields],
      }));
  }

  function updateAnalyticsEvidenceUi() {
    const metrics = analyticsMetrics();
    const selected = [];
    const verified = [];
    analyticsEvidenceGroups.forEach((group) => {
      const enabled = $(group.enabledId).checked;
      const card = document.querySelector(`[data-evidence-card="${group.key}"]`);
      card?.classList.toggle("is-enabled", enabled);
      [group.systemId, group.refId, group.retrievedId, group.fileId].forEach((id) => {
        $(id).disabled = !enabled;
      });
      [group.systemId, group.refId, group.retrievedId].forEach((id) => { $(id).required = enabled; });
      $(group.fileId).required = enabled && !/^[a-f0-9]{64}$/i.test($(group.shaId).value);
      const nonzero = group.metricFields.filter((field) => Number(metrics[field] || 0) > 0);
      const coverage = document.querySelector(`[data-evidence-coverage="${group.key}"]`);
      if (coverage) coverage.textContent = nonzero.length
        ? `Muss belegen: ${nonzero.map((field) => analyticsMetricLabels[field]).join(", ")}`
        : `Kann belegen: ${group.metricFields.map((field) => analyticsMetricLabels[field]).join(", ")}`;
      if (enabled) {
        selected.push(group.label);
        const complete = /^[a-f0-9]{64}$/i.test($(group.shaId).value)
          && Boolean($(group.systemId).value.trim())
          && Boolean($(group.refId).value.trim())
          && Boolean($(group.retrievedId).value);
        if (complete) verified.push(group.label);
      }
    });
    const summary = $("analyticsEvidenceSummary");
    if (!summary) return;
    const allVerified = selected.length > 0 && verified.length === selected.length;
    summary.className = `evidence-summary${allVerified ? "" : " is-missing"}`;
    summary.textContent = allVerified
      ? `${verified.length} Quellenbeleg${verified.length === 1 ? "" : "e"} geprüft · belegt ${verified.join(", ")}.`
      : selected.length
        ? `${selected.length} Quelle${selected.length === 1 ? "" : "n"} ausgewählt · ${verified.length} Belegdatei${verified.length === 1 ? "" : "en"} geprüft · fehlende Belege ergänzen.`
        : "Keine Quelle ausgewählt · ohne Beleg kann die Messung nicht gespeichert werden.";
  }

  function requireEvidenceForMetricInput(event) {
    const metricField = event.target.dataset.analyticsMetric;
    if (!metricField || Number(event.target.value || 0) <= 0) {
      updateAnalyticsEvidenceUi();
      return;
    }
    const group = analyticsEvidenceGroups.find((item) => item.metricFields.includes(metricField));
    if (group) $(group.enabledId).checked = true;
    updateAnalyticsEvidenceUi();
  }

  function analyticsPayload() {
    const evidence = analyticsEvidenceArtifacts();
    return {
      content_id: $("analyticsContentId").value.trim(),
      review_window: $("analyticsReviewWindow").value,
      ...analyticsMetrics(),
      source_system: "manual",
      source_ref: $("analyticsSourceRef").value.trim() || evidence[0]?.ref || "",
      period_start: analyticsTimestamp("analyticsPeriodStart"),
      period_end: analyticsTimestamp("analyticsPeriodEnd"),
      retrieved_at: analyticsTimestamp("analyticsRetrievedAt"),
      operator: authenticatedActor(),
      attribution_rule: $("analyticsAttributionRule").value.trim(),
      snapshot_sha256: $("analyticsSnapshotSha256").value.trim() || evidence[0]?.sha256 || "",
      evidence,
    };
  }

  function analyticsConsistencyError(payload) {
    if (!payload.content_id) return "Bitte zuerst eine fällige Auswertung auswählen.";
    if (!payload.source_ref) return "Bitte mindestens einen benannten Quellenbeleg vollständig eintragen.";
    if (payload.qualified_leads > payload.leads) return "Qualifizierte Leads dürfen die Gesamtzahl der Leads nicht übersteigen.";
    if (payload.booked_calls > payload.qualified_leads) return "Gebuchte Gespräche dürfen qualifizierte Leads nicht übersteigen.";
    if (payload.landing_page_conversions > payload.landing_page_visits) return "Landingpage-Abschlüsse dürfen Landingpage-Besuche nicht übersteigen.";
    if (payload.pipeline_value_eur > 0 && !(payload.qualified_leads || payload.booked_calls)) return "Pipeline-Wert benötigt mindestens einen qualifizierten Lead oder ein gebuchtes Gespräch.";
    if (!payload.period_start || !payload.period_end || !payload.retrieved_at) return "Bitte alle drei Zeitangaben vollständig eintragen.";
    if (new Date(payload.period_end) < new Date(payload.period_start)) return "Das Zeitraum-Ende darf nicht vor dem Beginn liegen.";
    if (new Date(payload.retrieved_at) < new Date(payload.period_end)) return "Der Abrufzeitpunkt darf nicht vor dem Zeitraum-Ende liegen.";
    if (new Date(payload.retrieved_at).getTime() > Date.now() + 5 * 60000) return "Der Abrufzeitpunkt darf nicht in der Zukunft liegen.";
    if (!Array.isArray(payload.evidence) || !payload.evidence.length) return "Bitte mindestens einen prüfbaren Quellenbeleg aktivieren.";
    if (payload.evidence.some((item) => !/^[a-f0-9]{64}$/.test(String(item.sha256 || "")))) return "Bitte für jeden aktiven Quellenbeleg die zugehörige Exportdatei auswählen.";
    const covered = new Set(payload.evidence.flatMap((item) => item.metric_fields || []));
    const missingEvidence = Object.keys(analyticsMetricLabels).filter((field) => Number(payload[field] || 0) > 0 && !covered.has(field));
    if (missingEvidence.length) return `Für diese Werte fehlt ein Quellenbeleg: ${missingEvidence.map((field) => analyticsMetricLabels[field]).join(", ")}.`;
    return "";
  }

  function analyticsEvidenceConfirmed(record, payload) {
    if (!Array.isArray(record?.evidence) || record.evidence.length < payload.evidence.length) return false;
    return payload.evidence.every((expected) => record.evidence.some((actual) => {
      const actualFields = new Set(Array.isArray(actual?.metric_fields) ? actual.metric_fields : []);
      const actualTime = new Date(actual?.retrieved_at || "").getTime();
      const expectedTime = new Date(expected.retrieved_at).getTime();
      return actual?.system === expected.system
        && actual?.ref === expected.ref
        && String(actual?.sha256 || "").toLowerCase() === expected.sha256
        && actualTime === expectedTime
        && expected.metric_fields.every((field) => actualFields.has(field));
    }));
  }

  function analyticsRecordCanBeCorrected(item) {
    const metricFieldsPresent = Object.keys(analyticsMetricInputIds).every((field) => Object.hasOwn(item, field));
    return metricFieldsPresent
      && item.source_system === "manual"
      && Boolean(item.source_ref && item.period_start && item.period_end && item.retrieved_at && item.operator && item.attribution_rule)
      && Array.isArray(item.evidence)
      && item.evidence.length > 0
      && /^[a-fA-F0-9]{64}$/.test(String(item.request_fingerprint || ""));
  }

  function prefillAnalyticsCorrection(contentId, reviewWindow) {
    const actor = requireAuthenticatedActor("Analytics-Korrektur");
    if (!actor) return;
    const item = state.performance.find((entry) => entry.content_id === contentId && entry.review_window === reviewWindow);
    if (!item || !analyticsRecordCanBeCorrected(item)) {
      const message = "Diese Messung enthält nicht alle aktuellen Kennzahlen- und Belegdaten. Eine verlustfreie Korrektur wird deshalb nicht geöffnet.";
      $("analyticsFormResult").className = "inline-result is-bad";
      $("analyticsFormResult").textContent = message;
      showToast(message);
      return;
    }
    Object.entries(analyticsMetricInputIds).forEach(([field, id]) => { $(id).value = String(item[field] ?? 0); });
    $("analyticsContentId").value = item.content_id;
    $("analyticsContentLabel").value = item.campaign || contentBusinessLabel(item.content_id, "Veröffentlichter Kampagneninhalt");
    $("analyticsReviewWindow").value = item.review_window;
    $("analyticsPeriodStart").value = localDateTimeValue(new Date(item.period_start));
    $("analyticsPeriodEnd").value = localDateTimeValue(new Date(item.period_end));
    $("analyticsRetrievedAt").value = localDateTimeValue(new Date(item.retrieved_at));
    $("analyticsSourceRef").value = item.source_ref;
    $("analyticsOperator").value = actor;
    $("analyticsAttributionRule").value = item.attribution_rule;
    $("analyticsSnapshotSha256").value = item.snapshot_sha256 || "";

    analyticsEvidenceGroups.forEach((group) => {
      const requiredFields = group.metricFields.filter((field) => Number(item[field] || 0) > 0);
      const artifact = item.evidence.find((candidate) => {
        const fields = new Set(Array.isArray(candidate?.metric_fields) ? candidate.metric_fields : []);
        return requiredFields.length
          ? requiredFields.every((field) => fields.has(field))
          : group.metricFields.some((field) => fields.has(field));
      });
      $(group.enabledId).checked = Boolean(artifact);
      if (artifact) {
        $(group.systemId).value = artifact.system || "";
        $(group.refId).value = artifact.ref || "";
        $(group.retrievedId).value = localDateTimeValue(new Date(artifact.retrieved_at));
        $(group.shaId).value = artifact.sha256 || "";
        $(group.proofId).className = "file-proof is-ready";
        $(group.proofId).textContent = "Bestehender Quellenbeleg bestätigt · nur bei geänderter Quelle neu auswählen";
      }
    });

    state.analyticsCorrection = {
      supersedesFingerprint: String(item.request_fingerprint).toLowerCase(),
      revision: Number(item.revision || 1),
    };
    $("analyticsSupersedesFingerprint").value = state.analyticsCorrection.supersedesFingerprint;
    $("analyticsCorrectionOperator").value = actor;
    $("analyticsCorrectionReason").value = "";
    $("analyticsCorrectedAt").value = localDateTimeValue(new Date());
    $("analyticsCorrectionContext").textContent = `Korrektur von Version ${state.analyticsCorrection.revision} · der bisherige Eintrag bleibt erhalten`;
    $("analyticsCorrectionPanel").hidden = false;
    $("analyticsCorrectionPanel").disabled = false;
    $("analyticsReviewWindow").disabled = true;
    $("submitAnalytics").textContent = "Korrigierte Messung prüfen und speichern";
    $("analyticsFormResult").className = "inline-result is-warn";
    $("analyticsFormResult").innerHTML = `<strong>Korrektur vorbereitet</strong><span>Die aktuelle Revision wurde vollständig übernommen. Ändern Sie den falschen Wert und prüfen Sie die zugehörigen Quellenbelege.</span>`;
    setAnalyticsEntryVisible(true);
    updateAnalyticsEvidenceUi();
    $("analyticsEntryPanel").scrollIntoView({ behavior: "smooth", block: "start" });
    $("analyticsCorrectionReason").focus({ preventScroll: true });
  }

  function exitAnalyticsCorrectionMode() {
    state.analyticsCorrection = null;
    $("analyticsCorrectionPanel").disabled = true;
    $("analyticsCorrectionPanel").hidden = true;
    $("analyticsReviewWindow").disabled = false;
    $("analyticsSupersedesFingerprint").value = "";
    $("analyticsSourceRef").value = "";
    $("analyticsCorrectionReason").value = "";
    $("submitAnalytics").textContent = "Messwerte prüfen und speichern";
  }

  function analyticsCorrectionFields(payload) {
    if (!state.analyticsCorrection) return payload;
    return {
      ...payload,
      supersedes_fingerprint: state.analyticsCorrection.supersedesFingerprint,
      correction_reason: $("analyticsCorrectionReason").value.trim(),
      correction_operator: authenticatedActor(),
      corrected_at: analyticsTimestamp("analyticsCorrectedAt"),
    };
  }

  async function submitAnalyticsEntry(event) {
    event.preventDefault();
    const actor = requireAuthenticatedActor(state.analyticsCorrection ? "Analytics-Korrektur" : "Analytics-Erfassung");
    if (!actor) return;
    $("analyticsOperator").value = actor;
    $("analyticsCorrectionOperator").value = actor;
    const form = $("analyticsEntryForm");
    if (!form.reportValidity()) return;
    const correctionMode = Boolean(state.analyticsCorrection);
    const payload = analyticsCorrectionFields(analyticsPayload());
    const consistencyError = analyticsConsistencyError(payload);
    if (consistencyError) {
      $("analyticsFormResult").className = "inline-result is-bad";
      $("analyticsFormResult").textContent = consistencyError;
      showToast(consistencyError);
      return;
    }
    const button = $("submitAnalytics");
    button.disabled = true;
    button.textContent = correctionMode ? "Korrektur wird geprüft …" : "Messwerte werden geprüft …";
    try {
      const response = await post(correctionMode ? "/workflows/analytics-review/correct" : "/workflows/analytics-review", payload);
      const record = response.record || response.performance?.record || null;
      const correctionConfirmed = !correctionMode || (
        response.status === "corrected"
        && response.correction?.supersedes_fingerprint === payload.supersedes_fingerprint
        && response.correction?.operator === payload.correction_operator
        && response.correction?.reason === payload.correction_reason
      );
      const provenanceConfirmed = record
        && record.source_system === "manual"
        && record.source_ref === payload.source_ref
        && record.operator === payload.operator
        && record.attribution_rule === payload.attribution_rule
        && analyticsEvidenceConfirmed(record, payload)
        && correctionConfirmed;
      if (provenanceConfirmed) {
        $("analyticsFormResult").className = "inline-result is-ok";
        $("analyticsFormResult").innerHTML = `<strong>${correctionMode ? `Korrektur als Revision ${escapeHtml(response.revision || "–")} gespeichert` : response.idempotent ? "Bereits identisch gespeichert" : "Geprüft gespeichert"}</strong><span>Entscheidung: ${escapeHtml(friendlyStatus(response.action))} · Herkunft, Zeitraum und ${payload.evidence.length} Quellenbeleg${payload.evidence.length === 1 ? "" : "e"} wurden vom Server bestätigt.</span>`;
        if (correctionMode) {
          exitAnalyticsCorrectionMode();
          form.reset();
          $("analyticsOperator").value = authenticatedActor();
          setAnalyticsTimeDefaults("72h", { force: true });
          updateAnalyticsEvidenceUi();
        }
        showToast(`${correctionMode ? "Korrektur" : "Messwerte"} gespeichert · ${friendlyStatus(response.action)}`);
        await refreshResults().catch(() => {
          console.warn("Die Messwerte wurden gespeichert; die Ansicht konnte nicht vollständig aktualisiert werden.");
          showToast("Messwerte gespeichert; die Ergebnisliste konnte nicht aktualisiert werden.");
        });
      } else {
        $("analyticsFormResult").className = "inline-result is-warn";
        $("analyticsFormResult").innerHTML = `<strong>Antwort ohne Herkunftsbestätigung</strong><span>Der Server hat die übermittelten Herkunftsfelder nicht bestätigt. Diese Messung wird hier nicht als nachvollziehbar gespeichert angezeigt.</span>`;
        showToast("Serverantwort ohne bestätigte Datenherkunft.");
      }
    } catch (error) {
      $("analyticsFormResult").className = "inline-result is-bad";
      $("analyticsFormResult").innerHTML = `<strong>Nicht gespeichert</strong><span>${escapeHtml(businessErrorMessage(error))}</span>`;
      handleError(error);
    } finally {
      button.disabled = !authenticatedActor();
      button.textContent = state.analyticsCorrection ? "Korrigierte Messung prüfen und speichern" : "Messwerte prüfen und speichern";
      applyBusinessReadiness();
    }
  }

  function performanceRecordMarkup(item) {
    const correctable = Boolean(authenticatedActor()) && analyticsRecordCanBeCorrected(item);
    const correction = item.correction && typeof item.correction === "object" ? item.correction : {};
    return `<div class="work-item performance-item">
      <div><strong>${escapeHtml(item.campaign || contentBusinessLabel(item.content_id, "Veröffentlichter Kampagneninhalt"))}</strong><small>${escapeHtml(friendlyDecisionReason(item.reason))}</small><small>Auswertung ${escapeHtml(item.revision || 1)}${correction.corrected_at ? ` · korrigiert ${formatDate(correction.corrected_at)}` : ""}</small></div>
      <span>${escapeHtml(reviewWindowLabel(item.review_window))}</span>
      <span class="status-tag ${statusClass(item.action)}">${escapeHtml(friendlyStatus(item.action))}</span>
      <div class="performance-actions"><small>${formatDate(item.created_at)}</small><button class="text-button" type="button" data-correct-analytics="${escapeHtml(item.content_id)}" data-correct-window="${escapeHtml(item.review_window)}" ${correctable ? "" : "disabled title=\"Vollständige Mess- und Belegdaten fehlen\""}>Messung korrigieren</button></div>
    </div>`;
  }

  async function refreshResults() {
    const reviewWindows = ["72h", "7d", "14d", "30d"];
    const [performance, leads, outbox, dueResults] = await Promise.all([
      request("/workflows/performance?limit=20").catch(() => ({ items: [], unavailable: true })),
      request("/workflows/leads?limit=20").catch(() => ({ items: [], unavailable: true })),
      request("/workflows/outbox?limit=20").catch(() => ({ items: [], unavailable: true })),
      Promise.all(reviewWindows.map((reviewWindow) => request(`/workflows/analytics/due?review_window=${encodeURIComponent(reviewWindow)}`).catch(() => ({ items: [], review_window: reviewWindow, unavailable: true })))),
    ]);
    const leadItems = leads.items || [];
    const perfItems = performance.items || [];
    state.performance = perfItems;
    const outboxItems = outbox.items || [];
    state.outbox = outboxItems;
    state.outboxAvailable = outbox.unavailable !== true;
    const qualified = leadItems.filter((item) => Number(item.qualification_score || 0) >= 60).length;
    const scheduled = state.recentAvailable
      ? currentContentVersions(state.recent).filter((item) => ["ready_to_schedule", "scheduled", "published"].includes(item.status)).length
      : "Nicht geladen";
    const metrics = [
      ["Echte Kampagnen", state.campaignsAvailable ? state.campaigns.length : "Nicht geladen", state.campaignsAvailable ? "K1–K5" : "Das Kampagnenportfolio ist derzeit nicht verfügbar"],
      ["Freigaben in der aktuellen Ansicht", scheduled, state.recentAvailable ? "bis zu 100 aktuelle Inhalte · bereit / geplant / live" : "Der Inhaltsstand ist derzeit nicht verfügbar"],
      ["Qualifizierte Reaktionen", leads.unavailable ? "Nicht geladen" : qualified, leads.unavailable ? "Die Reaktionsliste ist derzeit nicht verfügbar" : "letzte bis zu 20 Einträge"],
      ["Lernentscheidungen", performance.unavailable ? "Nicht geladen" : perfItems.length, performance.unavailable ? "Die Auswertungsliste ist derzeit nicht verfügbar" : "letzte bis zu 20 Einträge · alle Messfenster"],
    ];
    $("resultMetrics").innerHTML = metrics.map(([label, value, detail]) => `<article class="metric-card"><small>${escapeHtml(label)}</small><strong>${escapeHtml(value)}</strong><p>${escapeHtml(detail)}</p></article>`).join("");
    renderDueAnalytics(dueResults);
    $("outboxList").innerHTML = outboxItems.length ? outboxItems.map(outboxRecordMarkup).join("") : outbox.unavailable
      ? `<div class="notice notice-warn">Das Übergabeprotokoll konnte nicht geladen werden. Der Zustand externer Übergaben ist deshalb unbekannt.</div>`
      : `<div class="empty-compact"><strong>Noch keine Übergabe</strong><p>Es wurde noch kein Postiz- oder CRM-Entwurf vorbereitet.</p></div>`;
    bindPostizReconciliationActions();
    $("performanceList").innerHTML = perfItems.length ? perfItems.map(performanceRecordMarkup).join("") : `<div class="empty-state" style="min-height:190px"><p>${performance.unavailable ? "Auswertungen konnten nicht geladen werden." : "Noch keine echten Performance-Daten."}</p></div>`;
    document.querySelectorAll("[data-correct-analytics]").forEach((button) => button.addEventListener("click", () => prefillAnalyticsCorrection(button.dataset.correctAnalytics, button.dataset.correctWindow)));
    $("leadList").innerHTML = leadItems.length ? leadItems.map((item) => `<div class="work-item"><div><strong>${escapeHtml(item.company || "Qualifizierte Reaktion")}</strong><small>${escapeHtml(item.campaign || "Kampagne")}</small></div><span>Qualifizierung ${escapeHtml(item.qualification_score ?? "–")}/100</span><span class="status-tag ${item.routing_allowed ? "ok" : ""}">${escapeHtml(friendlyStatus(item.next_action))}</span><span>${formatDate(item.created_at)}</span></div>`).join("") : `<div class="empty-state" style="min-height:190px"><p>${leads.unavailable ? "Reaktionen konnten nicht geladen werden." : "Noch keine echten Reaktionen erfasst."}</p></div>`;
    setAnalyticsTimeDefaults($("analyticsReviewWindow").value);
    $("analyticsOperator").value = authenticatedActor();
    $("analyticsCorrectionOperator").value = authenticatedActor();
  }

  async function refreshSetup() {
    const phases = await request("/workflows/phase-status").catch(() => ({ status: "blocked", phases: [], integrations: { checks: [] }, business_capabilities: {} }));
    state.integrations = phases.integrations || { checks: [] };
    state.phases = phases;
    state.businessCapabilities = phases.business_capabilities || {};
    renderSetup();
    applyBusinessReadiness();
  }

  function renderSetup() {
    const capabilities = [
      ["research", "Recherche", "Öffentliche Quellen können aktuell geprüft und belegt werden."],
      ["content_generation", "Ideen & Texte", "Neue Entwürfe können mit lokaler KI erstellt werden."],
      ["media_generation", "Bild- & Video-Assets", "Assets werden extern erstellt und anschließend hier einer menschlichen Prüfung zugeordnet."],
      ["approval", "Freigabe", "Prüfentscheidungen werden einer geschützten, benannten Person zugeordnet."],
      ["scheduler_handoff", "Redaktionsplanung", "Freigegebene Entwürfe können kontrolliert zur Planung übergeben werden."],
    ];
    const actorReady = Boolean(authenticatedActor());
    const items = capabilities.map(([key, label, readyCopy]) => {
      const capability = businessCapability(key);
      return {
        key,
        label,
        readyCopy,
        ...capability,
        releaseReady: actorReady && capability.ready === true,
        actionRunnable: actorReady && capability.can_run === true,
      };
    });
    const greenCount = items.filter((item) => item.releaseReady).length;
    const textReleaseReady = actorReady && capabilityReady("research") && capabilityReady("content_generation");
    const textRunnable = actorReady && capabilityCanRun("research") && capabilityCanRun("content_generation");
    const textEvidenceDetail = controlledTextEvidenceMessage(
      capabilityReady("research"),
      capabilityReady("content_generation"),
    );
    $("readinessSummary").innerHTML = [
      ["Neue Inhalte", textReleaseReady ? "Bereit" : textRunnable ? "Prüflauf möglich" : "Pausiert", !actorReady ? "Geschützte Anmeldung erforderlich" : textRunnable && !textReleaseReady ? textEvidenceDetail : "Verfügbare Schritte sind unten aufgeführt"],
      ["Bestätigte Möglichkeiten", `${greenCount}/${items.length}`, "Nur erfolgreich geprüfte Arbeit wird als bereit angezeigt"],
      ["Bestehende Arbeit", "Bleibt erhalten", "Entwürfe, Quellen und Ergebnisse werden bei einer Sperre nicht gelöscht"],
    ].map(([label, value, detail]) => `<article class="readiness-card"><small>${escapeHtml(label)}</small><strong>${escapeHtml(value)}</strong><p>${escapeHtml(detail)}</p></article>`).join("");
    $("serviceGrid").innerHTML = items.map((item) => {
      const status = item.releaseReady ? "Bereit" : item.actionRunnable ? "Prüflauf möglich" : !actorReady ? "Anmeldung nötig" : item.status === "partial" ? "Prüfung offen" : "Gesperrt";
      const statusTone = item.releaseReady ? "ok" : item.status === "blocked" || !actorReady ? "bad" : "";
      const message = item.releaseReady
        ? item.readyCopy
        : !actorReady
          ? "Bitte über den geschützten Zugang als benannte Person anmelden."
          : item.business_message || "Diese Arbeit ist derzeit nicht verfügbar.";
      return `<article class="service-card ${item.releaseReady ? "is-ready" : item.status === "blocked" || !actorReady ? "is-blocked" : ""}"><div class="service-head"><h3>${escapeHtml(item.label)}</h3><span class="status-tag ${statusTone}">${escapeHtml(status)}</span></div><p>${escapeHtml(message)}</p></article>`;
    }).join("");
    const healthTone = textReleaseReady ? "signal-ok" : textRunnable ? "signal-warn" : "signal-bad";
    const healthCopy = textReleaseReady ? "Arbeit freigegeben" : textRunnable ? "Prüflauf möglich" : "Neue Erstellung pausiert";
    $("globalHealth").innerHTML = `<span class="signal ${healthTone}"></span><span>${healthCopy}</span>`;
  }

  async function refreshCore() {
    const [campaigns, recent, runs] = await Promise.all([
      request("/campaigns").catch(() => ({ items: [], unavailable: true })),
      request("/workflows/states?limit=100").catch(() => ({ items: [], unavailable: true })),
      request("/workflows/trend-research/runs?limit=20").catch(() => ({ items: [] })),
    ]);
    state.campaignsAvailable = campaigns.unavailable !== true;
    state.recentAvailable = recent.unavailable !== true;
    state.approvalDataAvailable = state.recentAvailable;
    if (state.campaignsAvailable) {
      state.campaigns = campaigns.items || [];
      if (state.selectedCampaign) {
        state.selectedCampaign = state.campaigns.find((item) => item.id === state.selectedCampaign.id) || null;
      }
    }
    if (state.recentAvailable) state.recent = recent.items || [];
    void runs;
    renderCampaigns();
    renderAttentionQueue();
    renderRecent();
    if (!state.integrations) {
      refreshSetup().catch(() => console.warn("Die Arbeitsfähigkeit konnte nicht aktualisiert werden."));
    } else {
      renderSetup();
    }
  }

  function handleError(error, toast = true) {
    console.warn("Eine Aktion wurde sicher beendet; technische Details bleiben in der Serverdiagnose.");
    if (toast) showToast(businessErrorMessage(error));
  }

  function bindEvents() {
    document.querySelectorAll("[data-route]").forEach((button) => button.addEventListener("click", () => setRoute(button.dataset.route)));
    document.querySelectorAll("[data-back-stage]").forEach((button) => button.addEventListener("click", () => setStudioStep(button.dataset.backStage)));
    $("toResearch").addEventListener("click", () => setStudioStep(2));
    $("toIdeas").addEventListener("click", () => setStudioStep(3));
    $("toReview").addEventListener("click", () => { renderSelectedReview(); setStudioStep(4); });
    $("runTrendScan").addEventListener("click", runTrendScan);
    $("generateConcepts").addEventListener("click", generateConcepts);
    $("approveConcept").addEventListener("click", sendConceptToReview);
    document.querySelectorAll('input[name="trendPlatform"]').forEach((input) => input.addEventListener("change", () => {
      resetTrendSelection({ inputsChanged: true });
      updateTrendSourceSelection();
    }));
    $("trendLookback").addEventListener("change", () => resetTrendSelection({ inputsChanged: true }));
    $("trendUserPrompt").addEventListener("input", () => {
      if (state.concept || state.selectedVariant) resetConceptSelection({ promptChanged: true });
    });
    $("createWeeklyPlan").addEventListener("click", createWeeklyPlan);
    $("refreshSetup").addEventListener("click", () => refreshSetup().then(() => showToast("Dienste wurden neu geprüft.")).catch(handleError));
    $("refreshResults").addEventListener("click", () => refreshResults().then(() => showToast("Ergebnisse und Übergaben wurden aktualisiert.")).catch(handleError));
    $("analyticsEntryForm").addEventListener("submit", submitAnalyticsEntry);
    $("analyticsReviewWindow").addEventListener("change", (event) => setAnalyticsTimeDefaults(event.target.value, { force: true }));
    analyticsEvidenceGroups.forEach((group) => $(group.enabledId).addEventListener("change", updateAnalyticsEvidenceUi));
    analyticsEvidenceGroups.forEach((group) => $(group.fileId).addEventListener("change", () => verifySelectedFile({
      fileId: group.fileId,
      shaId: group.shaId,
      proofId: group.proofId,
      refId: group.refId,
    }).then(updateAnalyticsEvidenceUi)));
    Object.entries(analyticsMetricInputIds).forEach(([field, id]) => {
      $(id).dataset.analyticsMetric = field;
      $(id).addEventListener("input", requireEvidenceForMetricInput);
    });
    $("cancelAnalyticsCorrection").addEventListener("click", exitAnalyticsCorrectionMode);
    updateAnalyticsEvidenceUi();
    updateTrendSourceSelection();
    window.addEventListener("hashchange", () => setRoute(location.hash.slice(1), { updateHash: false }));
  }

  async function boot() {
    $("todayLabel").textContent = new Intl.DateTimeFormat("de-DE", { weekday: "long", day: "2-digit", month: "long" }).format(new Date());
    bindEvents();
    await refreshSession();
    setRoute(location.hash.slice(1) || "overview", { updateHash: false });
    try { await refreshCore(); }
    catch (error) {
      handleError(error);
      $("overviewCampaigns").innerHTML = `<div class="notice notice-bad">${escapeHtml(businessErrorMessage(error))}</div>`;
    }
  }

  boot();
})();
