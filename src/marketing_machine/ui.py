from __future__ import annotations


def render_marketing_console() -> str:
    """Render the campaign-first console shell.

    The browser application lives in versioned static assets so the product UI
    can evolve without turning this Python module into a multi-thousand-line
    HTML/JavaScript blob.
    """

    return """<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#102f2b">
  <title>WAMOCON Marketing-Konsole</title>
  <link rel="stylesheet" href="/static/console.css?v=20260714">
</head>
<body>
  <div class="app-shell">
    <aside class="side-nav" aria-label="Hauptnavigation">
      <a class="brand" href="#overview" aria-label="WAMOCON Marketing-Konsole – Übersicht">
        <span class="brand-mark" aria-hidden="true">W</span>
        <span><strong>WAMOCON</strong><small>Marketing Studio</small></span>
      </a>
      <nav class="primary-nav">
        <button class="nav-link is-active" type="button" data-route="overview" aria-current="page"><span>01</span>Übersicht</button>
        <button class="nav-link" type="button" data-route="campaigns"><span>02</span>Kampagnen</button>
        <button class="nav-link" type="button" data-route="studio"><span>03</span>Content Studio</button>
        <button class="nav-link" type="button" data-route="approvals"><span>04</span>Freigaben <b id="navReviewCount">0</b></button>
        <button class="nav-link" type="button" data-route="results"><span>05</span>Ergebnisse</button>
      </nav>
      <div class="side-footer">
        <button class="nav-link secondary" type="button" data-route="setup"><span>✓</span>Arbeitsfähigkeit</button>
        <p>Kein Auto-Publishing.<br>Ein Mensch entscheidet final.</p>
      </div>
    </aside>

    <main class="main-shell">
      <header class="topbar">
        <div>
          <p class="eyebrow" id="pageEyebrow">MARKETING-ARBEITSPLATZ</p>
          <h1 id="pageTitle">Guten Morgen.</h1>
          <p class="page-subtitle" id="pageSubtitle">Hier sehen Sie, was heute wirklich Aufmerksamkeit braucht.</p>
        </div>
        <div class="top-actions">
          <div class="session-chip is-pending" id="sessionIdentity" role="status" aria-live="polite"><span class="signal signal-warn"></span><span>Identität wird geprüft</span></div>
          <button class="health-chip" type="button" data-route="setup" id="globalHealth" aria-live="polite">
            <span class="signal signal-warn"></span><span>System wird geprüft</span>
          </button>
          <button class="button button-primary" type="button" data-route="studio">+ Content erstellen</button>
        </div>
      </header>

      <div class="business-guard is-blocked" id="businessGuard" role="status" aria-live="polite">
        <span class="signal signal-warn"></span>
        <div><strong>Arbeitsfreigabe wird geprüft</strong><p>Neue Erstellung bleibt gesperrt, bis alle notwendigen Prüfungen bestätigt sind.</p></div>
        <button class="text-button" type="button" data-route="setup">Status ansehen →</button>
      </div>

      <div class="workspace" id="workspace">
        <section class="view is-active" id="view-overview" data-view="overview">
          <div class="overview-grid">
            <article class="editorial-intro">
              <p class="eyebrow">HEUTE · <span id="todayLabel"></span></p>
              <h2>Fünf echte Kampagnen.<br><em>Ein klarer nächster Schritt.</em></h2>
              <p>Demo-Daten bleiben ausgeblendet. Jede Zahl hier kommt aus Ihren fünf Kampagnen und dem tatsächlichen Freigabeprozess.</p>
              <div class="intro-actions">
                <button class="button button-primary" type="button" data-route="studio">Neue Idee entwickeln</button>
                <button class="button button-quiet" type="button" data-route="approvals">Offene Entwürfe prüfen</button>
              </div>
            </article>
            <aside class="attention-card" aria-labelledby="attentionTitle">
              <div class="section-label"><span>Prioritäten</span><small id="attentionCount">0 offen</small></div>
              <h3 id="attentionTitle">Was jetzt zu tun ist</h3>
              <div id="attentionQueue" class="attention-list" aria-live="polite"></div>
            </aside>
          </div>

          <div class="section-heading">
            <div><p class="eyebrow">PORTFOLIO</p><h2>Ihre Kampagnen</h2></div>
            <button class="text-button" type="button" data-route="campaigns">Alle Details →</button>
          </div>
          <div class="campaign-grid" id="overviewCampaigns" role="region" aria-label="Kampagnenübersicht" aria-live="polite" tabindex="0"></div>

          <div class="lower-grid">
            <article class="surface-panel">
              <div class="panel-heading"><div><p class="eyebrow">CONTENT-FLUSS</p><h3>Aktuelle Arbeit</h3></div><button class="text-button" type="button" data-route="approvals">Zur Freigabe →</button></div>
              <div id="recentWork" class="work-list"></div>
            </article>
            <article class="surface-panel week-panel">
              <div class="panel-heading"><div><p class="eyebrow">WOCHENZIEL</p><h3>Fortschritt</h3></div><strong id="portfolioProgress">0%</strong></div>
              <div class="large-progress" role="progressbar" aria-label="Fortschritt des Wochenziels" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><span id="portfolioProgressBar"></span></div>
              <p id="portfolioProgressCopy">Kampagnendaten werden geladen.</p>
              <button class="button button-dark" type="button" id="createWeeklyPlan" disabled>Wochenentwürfe für aktive Kampagnen erstellen</button>
            </article>
          </div>
        </section>

        <section class="view" id="view-campaigns" data-view="campaigns">
          <div class="compact-hero">
            <div><p class="eyebrow">DIE FÜNF ECHTEN KAMPAGNEN</p><h2>Vom Ziel zur Veröffentlichung</h2><p>Status, Quellenlage, Content-Fortschritt und nächster Schritt – ohne technische Ablenkung.</p></div>
            <button class="button button-primary" type="button" data-route="studio">Content erstellen</button>
          </div>
          <div class="campaign-list" id="campaignList"></div>
        </section>

        <section class="view" id="view-studio" data-view="studio">
          <div class="studio-layout">
            <aside class="studio-stepper" aria-label="Content-Prozess">
              <p class="eyebrow">CONTENT STUDIO</p>
              <h2>Eine Idee.<br>Sauber belegt.</h2>
              <ol>
                <li class="is-active" data-studio-step="1" aria-current="step"><span>1</span><div><strong>Kampagne & Format</strong><small>Ziel und Ausgabe prüfen</small></div></li>
                <li data-studio-step="2"><span>2</span><div><strong>Recherche</strong><small>Aktuelle Quellen prüfen</small></div></li>
                <li data-studio-step="3"><span>3</span><div><strong>Richtungen</strong><small>Ideen bewusst vergleichen</small></div></li>
                <li data-studio-step="4"><span>4</span><div><strong>KI-Entwurf</strong><small>Auswahl vollständig ausarbeiten</small></div></li>
              </ol>
              <div class="guard-note"><span>✓</span><p><strong>Sicherheitsregel</strong>Unbelegte Trends können nicht zur Freigabe gesendet werden.</p></div>
            </aside>

            <div class="studio-main">
              <div id="studioCampaignSummary" class="studio-selection-summary" aria-live="polite" hidden></div>
              <section class="studio-stage is-active" data-stage="1">
                <div class="stage-heading"><div><p class="eyebrow">SCHRITT 1 VON 4</p><h2>Was möchten Sie veröffentlichen?</h2><p>Wählen Sie eine der fünf realen Kampagnen. Zielgruppe, Angebot, Kanal und passendes Ausgabeformat werden verlässlich übernommen.</p></div></div>
                <div class="studio-campaign-picker" id="studioCampaignPicker"></div>
                <div class="stage-actions"><span></span><button class="button button-primary" id="toResearch" type="button" disabled>Weiter zur Recherche →</button></div>
              </section>

              <section class="studio-stage" data-stage="2">
                <div class="stage-heading split"><div><p class="eyebrow">SCHRITT 2 VON 4</p><h2>Was bewegt die Zielgruppe gerade?</h2><p>Wir suchen nur in öffentlichen Quellen und zeigen jede Referenz zur Prüfung.</p></div><button class="button button-quiet" type="button" data-back-stage="1">← Kampagne ändern</button></div>
                <div class="research-controls">
                  <label>Zeitraum<select id="trendLookback"><option value="7">7 Tage</option><option value="10" selected>10 Tage</option><option value="30">30 Tage</option></select></label>
                  <fieldset aria-describedby="trendSourceGate"><legend>Quellen</legend><label><input type="checkbox" name="trendPlatform" value="web" checked> Web</label><label><input type="checkbox" name="trendPlatform" value="instagram" checked> Instagram</label><label><input type="checkbox" name="trendPlatform" value="tiktok" checked> TikTok</label><label><input type="checkbox" name="trendPlatform" value="reddit" checked> Reddit</label><p id="trendSourceGate" class="source-selection-note" role="status">Mindestens eine öffentliche Quelle auswählen.</p></fieldset>
                  <button class="button button-dark" type="button" id="runTrendScan" disabled>Aktuelle Trends recherchieren</button>
                </div>
                <div class="job-progress is-hidden" id="researchProgress" aria-live="polite" aria-busy="false">
                  <div class="progress-orbit"><span></span></div>
                  <div><strong id="researchProgressTitle">Öffentliche Quellen werden durchsucht …</strong><p id="researchProgressDetail">Quellen finden · Datum prüfen · Kampagnenfit bewerten</p></div>
                </div>
                <div id="researchGate" class="notice notice-neutral">Starten Sie die Recherche. Ohne verifizierte Quellen bleibt die Trend-Weiterleitung gesperrt.</div>
                <div class="trend-results" id="trendResults"></div>
                 <div class="stage-actions"><button class="button button-quiet" type="button" data-back-stage="1">← Zurück</button><button class="button button-primary" id="toIdeas" type="button" disabled>Richtungen vorbereiten →</button></div>
              </section>

              <section class="studio-stage" data-stage="3">
                <div class="stage-heading split"><div><p class="eyebrow">SCHRITT 3 VON 4</p><h2>Welche Idee trägt die Botschaft am besten?</h2><p>Vergleichen Sie Idee, Einstieg, Ablauf, Visuals und Caption. Das vorgesehene Kampagnenformat bleibt dabei verbindlich.</p></div><button class="button button-quiet" type="button" data-back-stage="2">← Trend ändern</button></div>
                <label class="creator-note">Ihre Richtung für die Varianten <span>optional</span><textarea id="trendUserPrompt" rows="2" placeholder="z. B. stärkeres Q&A, sachlicher, mehr Bildschirmaufnahme …"></textarea></label>
                <div class="job-progress is-hidden" id="ideaProgress" aria-live="polite" aria-busy="false"><div class="progress-orbit"><span></span></div><div><strong>Vier belegte redaktionelle Richtungen werden vorbereitet …</strong><p>Idee · Einstieg · Ablauf · Visuals · Caption · Handlungsaufforderung</p></div></div>
                <div id="conceptGate" class="notice notice-neutral">Bereiten Sie vier belegte Richtungen vor. Die lokale KI erstellt erst nach Ihrer bewussten Auswahl den vollständigen Entwurf.</div>
                <button class="button button-dark generate-button" type="button" id="generateConcepts" disabled>4 Richtungen vorbereiten</button>
                <div class="concept-grid" id="conceptResults"></div>
                 <div class="stage-actions"><button class="button button-quiet" type="button" data-back-stage="2">← Zurück</button><button class="button button-primary" id="toReview" type="button" disabled>Auswahl prüfen →</button></div>
              </section>

              <section class="studio-stage" data-stage="4">
                <div class="stage-heading"><div><p class="eyebrow">SCHRITT 4 VON 4</p><h2>Ihre Richtung für den KI-Entwurf.</h2><p>Nach Ihrer Bestätigung erstellt die lokale KI den vollständigen Kampagnenentwurf. Nichts wird automatisch veröffentlicht.</p></div></div>
                <div id="selectedConceptReview" class="selected-review"></div>
                <div class="job-progress is-hidden" id="finalDraftProgress" aria-live="polite" aria-busy="false"><div class="progress-orbit"><span></span></div><div><strong>Lokale KI erstellt den vollständigen Entwurf …</strong><p>Inhalt · Format · Caption · Quellenbezug · Qualitätsprüfung</p></div></div>
                <div class="approval-strip"><span class="signal signal-ok"></span><div><strong>Nach der Erstellung</strong><p>Nur ein erfolgreich erzeugter KI-Entwurf erscheint unter Freigaben. Danach folgen Fakten-, Datenschutz- und Markenprüfung.</p></div></div>
                <div class="stage-actions"><button class="button button-quiet" type="button" data-back-stage="3">← Auswahl ändern</button><button class="button button-primary" type="button" id="approveConcept" disabled>Mit lokaler KI als Entwurf erstellen</button></div>
              </section>
            </div>
          </div>
        </section>

        <section class="view" id="view-approvals" data-view="approvals">
          <div class="compact-hero"><div><p class="eyebrow">MENSCHLICHE FREIGABE</p><h2>Prüfen, bevor etwas nach außen geht.</h2><p>Links wählen Sie den Entwurf. Rechts sehen Sie Inhalt, Quellen und alle Pflichtprüfungen.</p></div></div>
          <div class="approval-workspace">
            <aside class="review-queue"><div class="queue-head"><div><h3>Prüfen & übergeben</h3><small>Freigaben und Postiz-Entwürfe</small></div><span id="reviewCount">0</span></div><div id="reviewQueue"></div></aside>
            <div class="review-detail" id="reviewDetail" aria-live="polite"><div class="empty-state"><span>✓</span><h3>Entwurf auswählen</h3><p>Hier erscheint die vollständige Content-Vorschau.</p></div></div>
          </div>
        </section>

        <section class="view" id="view-results" data-view="results">
          <div class="compact-hero"><div><p class="eyebrow">LERNEN & VERBESSERN</p><h2>Ergebnisse, die Entscheidungen auslösen.</h2><p>Keine reinen Reichweitenzahlen: qualifizierte Reaktionen, Leads, Gespräche und nächste Maßnahmen.</p></div></div>
          <div class="metric-row" id="resultMetrics"></div>
          <div class="result-operations-grid">
            <article class="surface-panel due-panel">
              <div class="panel-heading"><div><p class="eyebrow">HEUTE MESSEN</p><h3>Fällige Auswertungen</h3></div><span class="panel-count" id="analyticsDueCount">0</span></div>
              <p class="panel-intro">Nur veröffentlichte Inhalte mit fälligem Messfenster erscheinen hier. Ein Klick übernimmt Inhalt und Zeitraum in das Formular.</p>
              <div id="analyticsDueList" class="due-list" aria-live="polite"></div>
            </article>
            <article class="surface-panel outbox-panel">
              <div class="panel-heading"><div><p class="eyebrow">ÜBERGABEPROTOKOLL</p><h3>Externe Entwürfe</h3></div><button class="text-button" type="button" id="refreshResults">Aktualisieren</button></div>
              <p class="panel-intro">Hier steht, ob eine Übergabe nur vorbereitet, bestätigt gesendet oder noch mit dem Anbieter abzugleichen ist.</p>
              <div id="outboxList" class="handoff-list" aria-live="polite"></div>
            </article>
          </div>
          <article class="surface-panel analytics-entry-panel" id="analyticsEntryPanel">
            <div class="panel-heading"><div><p class="eyebrow">NACHVOLLZIEHBARE MANUELLE ERFASSUNG</p><h3>Messwerte mit Herkunft eintragen</h3></div><span class="status-tag">Quelle: manuell</span></div>
            <p class="panel-intro">Tragen Sie nur Werte aus einem überprüfbaren Export oder Bericht ein. Zeitraum, Abrufzeit, verantwortliche Person und Zuordnungsregel werden gemeinsam mit der Entscheidung gespeichert.</p>
            <div id="analyticsSelectionGate" class="empty-compact"><strong>Zuerst eine Messaufgabe auswählen</strong><p>Wählen Sie oben eine fällige Auswertung. Danach öffnet sich das passende Formular mit Inhalt und Messzeitraum.</p></div>
            <form id="analyticsEntryForm" class="analytics-form" hidden>
              <fieldset>
                <legend>1 · Inhalt und Messfenster</legend>
                <input type="hidden" id="analyticsContentId">
                <div class="form-grid form-grid-four">
                  <label>Ausgewählter Inhalt<input type="text" id="analyticsContentLabel" readonly required placeholder="Bitte oben eine fällige Auswertung auswählen"></label>
                  <label>Messfenster<select id="analyticsReviewWindow" required><option value="72h">72 Stunden</option><option value="7d">7 Tage</option><option value="14d">14 Tage</option><option value="30d">30 Tage</option></select></label>
                  <label>Zeitraum von<input type="datetime-local" id="analyticsPeriodStart" required></label>
                  <label>Zeitraum bis<input type="datetime-local" id="analyticsPeriodEnd" required></label>
                </div>
              </fieldset>
              <fieldset>
                <legend>2 · Sichtbarkeit und Reaktionen</legend>
                <div class="form-grid form-grid-six">
                  <label>Impressionen<input type="number" id="analyticsImpressions" min="0" step="1" value="0" required></label>
                  <label>Gespeichert<input type="number" id="analyticsSaves" min="0" step="1" value="0" required></label>
                  <label>Geteilt<input type="number" id="analyticsShares" min="0" step="1" value="0" required></label>
                  <label>Käufer-Kommentare<input type="number" id="analyticsBuyerComments" min="0" step="1" value="0" required></label>
                  <label>Profilbesuche<input type="number" id="analyticsProfileVisits" min="0" step="1" value="0" required></label>
                  <label>Klicks<input type="number" id="analyticsClicks" min="0" step="1" value="0" required></label>
                </div>
              </fieldset>
              <fieldset>
                <legend>3 · Interessenten und Geschäftswert</legend>
                <div class="form-grid form-grid-six">
                  <label>Leads<input type="number" id="analyticsLeads" min="0" step="1" value="0" required></label>
                  <label>Qualifizierte Leads<input type="number" id="analyticsQualifiedLeads" min="0" step="1" value="0" required></label>
                  <label>Gebuchte Gespräche<input type="number" id="analyticsBookedCalls" min="0" step="1" value="0" required></label>
                  <label>Landingpage-Besuche<input type="number" id="analyticsLandingVisits" min="0" step="1" value="0" required></label>
                  <label>Landingpage-Abschlüsse<input type="number" id="analyticsLandingConversions" min="0" step="1" value="0" required></label>
                  <label>Pipeline-Wert in €<input type="number" id="analyticsPipelineValue" min="0" step="0.01" value="0" required></label>
                </div>
              </fieldset>
              <fieldset>
                <legend>4 · Prüfbare Herkunft</legend>
                <input type="hidden" id="analyticsSourceRef">
                <div class="form-grid form-grid-two">
                  <label>Abgerufen am<input type="datetime-local" id="analyticsRetrievedAt" required></label>
                  <label>Verantwortliche Person<input type="text" id="analyticsOperator" autocomplete="name" required readonly aria-describedby="sessionIdentity" placeholder="Aus der geschützten Anmeldung"></label>
                  <label>Zuordnungsregel<input type="text" id="analyticsAttributionRule" required placeholder="z. B. letzter Kampagnenkontakt vor Lead-Erfassung"></label>
                </div>
                <input type="hidden" id="analyticsSnapshotSha256">
              </fieldset>
              <fieldset class="analytics-evidence-fieldset">
                <legend>5 · Belege je Kennzahlengruppe</legend>
                <p class="fieldset-intro">Jeder Wert größer als null muss durch einen konkreten, unveränderten Export belegt sein. Aktivieren Sie nur die Quellen, die Sie wirklich geprüft haben; ein Beleg deckt ausschließlich die angezeigten Kennzahlen ab.</p>
                <div class="analytics-evidence-grid">
                  <article class="analytics-evidence-card is-enabled" data-evidence-card="engagement">
                    <div class="evidence-card-heading">
                      <div><strong>Interaktion & Reichweite</strong><small data-evidence-coverage="engagement">Impressionen, Reaktionen, Profilbesuche und Klicks</small></div>
                      <label class="evidence-toggle"><input type="checkbox" id="analyticsEvidenceEngagementEnabled" checked><span>Quelle verwenden</span></label>
                    </div>
                    <div class="evidence-fields">
                      <label>System<input type="text" id="analyticsEvidenceEngagementSystem" required maxlength="100" value="Postiz" placeholder="z. B. Postiz"></label>
                      <label>Export oder Bericht<input type="text" id="analyticsEvidenceEngagementRef" required maxlength="1000" placeholder="Dateiname oder Berichtsreferenz"></label>
                      <label>Export abgerufen am<input type="datetime-local" id="analyticsEvidenceEngagementRetrievedAt" required></label>
                      <label>Belegdatei auswählen <span>bleibt auf diesem Gerät</span><input type="file" id="analyticsEvidenceEngagementFile" required accept=".csv,.xlsx,.xls,.pdf,.json,.zip,.png,.jpg,.jpeg"></label>
                      <input type="hidden" id="analyticsEvidenceEngagementSha256">
                      <p class="file-proof" id="analyticsEvidenceEngagementProof" role="status">Noch keine Belegdatei geprüft.</p>
                    </div>
                  </article>
                  <article class="analytics-evidence-card" data-evidence-card="landing">
                    <div class="evidence-card-heading">
                      <div><strong>Landingpage</strong><small data-evidence-coverage="landing">Besuche und Abschlüsse</small></div>
                      <label class="evidence-toggle"><input type="checkbox" id="analyticsEvidenceLandingEnabled"><span>Quelle verwenden</span></label>
                    </div>
                    <div class="evidence-fields">
                      <label>System<input type="text" id="analyticsEvidenceLandingSystem" maxlength="100" value="Landingpage-Analytics" placeholder="z. B. Matomo"></label>
                      <label>Export oder Bericht<input type="text" id="analyticsEvidenceLandingRef" maxlength="1000" placeholder="Dateiname oder Berichtsreferenz"></label>
                      <label>Export abgerufen am<input type="datetime-local" id="analyticsEvidenceLandingRetrievedAt"></label>
                      <label>Belegdatei auswählen <span>bleibt auf diesem Gerät</span><input type="file" id="analyticsEvidenceLandingFile" accept=".csv,.xlsx,.xls,.pdf,.json,.zip,.png,.jpg,.jpeg"></label>
                      <input type="hidden" id="analyticsEvidenceLandingSha256">
                      <p class="file-proof" id="analyticsEvidenceLandingProof" role="status">Noch keine Belegdatei geprüft.</p>
                    </div>
                  </article>
                  <article class="analytics-evidence-card" data-evidence-card="crm">
                    <div class="evidence-card-heading">
                      <div><strong>CRM & Pipeline</strong><small data-evidence-coverage="crm">Leads, Qualifizierung, Gespräche und Pipeline-Wert</small></div>
                      <label class="evidence-toggle"><input type="checkbox" id="analyticsEvidenceCrmEnabled"><span>Quelle verwenden</span></label>
                    </div>
                    <div class="evidence-fields">
                      <label>System<input type="text" id="analyticsEvidenceCrmSystem" maxlength="100" value="CRM" placeholder="z. B. Twenty CRM"></label>
                      <label>Export oder Bericht<input type="text" id="analyticsEvidenceCrmRef" maxlength="1000" placeholder="Dateiname oder Berichtsreferenz"></label>
                      <label>Export abgerufen am<input type="datetime-local" id="analyticsEvidenceCrmRetrievedAt"></label>
                      <label>Belegdatei auswählen <span>bleibt auf diesem Gerät</span><input type="file" id="analyticsEvidenceCrmFile" accept=".csv,.xlsx,.xls,.pdf,.json,.zip,.png,.jpg,.jpeg"></label>
                      <input type="hidden" id="analyticsEvidenceCrmSha256">
                      <p class="file-proof" id="analyticsEvidenceCrmProof" role="status">Noch keine Belegdatei geprüft.</p>
                    </div>
                  </article>
                </div>
                <div id="analyticsEvidenceSummary" class="evidence-summary" aria-live="polite">1 Quellenbeleg aktiv · deckt Interaktion & Reichweite ab.</div>
              </fieldset>
              <fieldset id="analyticsCorrectionPanel" class="analytics-correction-panel" hidden disabled>
                <legend>6 · Nachvollziehbare Korrektur</legend>
                <div class="notice notice-warn"><strong>Der ursprüngliche Eintrag bleibt erhalten.</strong><br>Die Korrektur erzeugt eine neue Version und wird nachvollziehbar mit dem bisherigen Eintrag verknüpft. Ändern Sie nur Werte, die Sie anhand der Belege erneut geprüft haben.</div>
                <input type="hidden" id="analyticsSupersedesFingerprint">
                <div class="form-grid form-grid-two">
                  <label>Korrigiert von<input type="text" id="analyticsCorrectionOperator" autocomplete="name" maxlength="200" required readonly aria-describedby="sessionIdentity" placeholder="Aus der geschützten Anmeldung"></label>
                  <label>Korrigiert am<input type="datetime-local" id="analyticsCorrectedAt" required></label>
                </div>
                <label class="full-field">Grund der Korrektur <span>mindestens 10 Zeichen</span><textarea id="analyticsCorrectionReason" rows="3" minlength="10" maxlength="1000" required placeholder="Welcher Wert war falsch, warum und welcher Beleg bestätigt die Änderung?"></textarea></label>
                <div class="correction-footer"><span id="analyticsCorrectionContext">Keine Korrektur aktiv.</span><button class="text-button" type="button" id="cancelAnalyticsCorrection">Korrektur abbrechen</button></div>
              </fieldset>
              <div class="analytics-submit-row">
                <div id="analyticsFormResult" class="inline-result" role="status" aria-live="polite">Noch keine Messwerte übermittelt.</div>
                <button class="button button-dark" type="submit" id="submitAnalytics" disabled>Messwerte prüfen und speichern</button>
              </div>
            </form>
          </article>
          <div class="lower-grid">
            <article class="surface-panel"><div class="panel-heading"><div><p class="eyebrow">ENTSCHEIDUNGEN</p><h3>Letzte Auswertungen</h3></div></div><div id="performanceList" class="work-list"></div></article>
            <article class="surface-panel"><div class="panel-heading"><div><p class="eyebrow">REAKTIONEN</p><h3>Leads & Übergaben</h3></div></div><div id="leadList" class="work-list"></div></article>
          </div>
        </section>

        <section class="view" id="view-setup" data-view="setup">
          <div class="compact-hero"><div><p class="eyebrow">ARBEITSFÄHIGKEIT</p><h2>Welche Marketingarbeit ist heute möglich?</h2><p>Hier sehen Sie nur die fachlichen Möglichkeiten und den nächsten sinnvollen Schritt. Technische Details übernimmt die Betreuung.</p></div><button class="button button-dark" id="refreshSetup" type="button">Neu prüfen</button></div>
          <div class="readiness-summary" id="readinessSummary"></div>
          <div class="service-grid" id="serviceGrid"></div>
        </section>
      </div>
    </main>

    <nav class="mobile-nav" aria-label="Mobile Navigation">
      <button class="is-active" data-route="overview" aria-current="page"><span>⌂</span>Übersicht</button>
      <button data-route="campaigns"><span>◫</span>Kampagnen</button>
      <button class="create" data-route="studio"><span>＋</span>Erstellen</button>
      <button data-route="approvals"><span>✓</span>Freigaben</button>
      <button data-route="results"><span>↗</span>Ergebnisse</button>
    </nav>
  </div>
  <div class="toast" id="toast" role="status" aria-live="polite"></div>
  <script src="/static/console.js?v=20260714"></script>
</body>
</html>"""
