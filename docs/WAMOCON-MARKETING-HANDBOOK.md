# WAMOCON Marketing-Maschine

## Betriebs- und Anwenderhandbuch

**Einfacher Arbeitsablauf für Marketing · kontrollierter Betrieb für Administration**

> **Betriebsstatus am 13. Juli 2026: NICHT produktionsbereit.**

> Die Live-Konsole wurde zuletzt unverschlüsselt über HTTP beobachtet; beim abschließenden Büro-Netzwerkcheck war Nvidia-1 jedoch nicht mehr auflösbar oder per SSH erreichbar. Die geschützte HTTPS-/Identitätsstrecke fehlt, der zuletzt beobachtete n8n-LAN-Endpunkt war fehlerhaft und der Live-Workflowbestand wich vom freigegebenen Manifest ab. Marketing-Mitarbeitende dürfen den Bestand erst nach bestätigter Wiederherstellung lesend ansehen und bis zur dokumentierten Freigabe keine neuen Inhalte erstellen, freigeben oder an externe Dienste übergeben. Externe Schreibvorgänge bleiben deaktiviert.

---

## Dokumentenlenkung

| Feld | Wert |
| --- | --- |
| Dokument | WAMOCON Marketing-Maschine – Betriebs- und Anwenderhandbuch |
| Version | 1.5 |
| Stand | 13. Juli 2026 |
| Status | Kontrollierte Fassung; Live-System gesperrt bis Release-Abnahme |
| Zielgruppe | Marketing-Anwender ohne technischen Hintergrund; Freigebende; Systemadministration |
| Dokumentverantwortung | Marketing Operations |
| Technische Verantwortung | IT-/Plattformbetrieb |
| Freigabeverantwortung | Benannte Marketing- oder Geschäftsverantwortung |
| Nächste Prüfung | Nach jedem Release oder spätestens quartalsweise |
| Gültiger Umfang | Genau die fünf Kampagnen K1 bis K5, Content- und Reel-Erstellung, Quellen, Freigaben, Postiz-Entwürfe, Messung und technischer Betrieb |
| Nicht enthalten | Zugangsdaten, Tokens, private Schlüssel, personenbezogene Einwilligungsdokumente und interne Beweisdateien |
| Verbindliche Regel | KI recherchiert und entwirft; ein namentlich identifizierter Mensch entscheidet |

Dieses Handbuch verbindet vier Dokumentarten: eine kurze Einführung, konkrete Arbeitsanweisungen, Status- und Systemreferenzen sowie Erklärungen zu Sicherheitsgrenzen. Bei Widersprüchen gilt in dieser Reihenfolge: aktuelle Change-Freigabe, technische Release-Abnahme, Governance-Regeln, dieses Handbuch, ältere Validierungsberichte.

### Verbindliche Projektquellen

- Kampagnen und Wochenziele: [`campaign_catalog.py`](../src/marketing_machine/campaign_catalog.py) und [`Kampagnen/`](../Kampagnen/)
- Zielgruppenprofile: [`Zielgruppen/`](../Zielgruppen/) – nur als redaktioneller Kontext, nie als Beleg für öffentliche Aussagen
- Governance: [`governance-policy.json`](../config/governance-policy.json), [`compliance-guardrails.md`](compliance-guardrails.md) und [`evidence-vault.md`](evidence-vault.md)
- Freigabefähiger n8n-Sollzustand: [`release_acceptance.py`](../scripts/release_acceptance.py)
- Technische Wartung: [`remote-project-runbook.md`](remote-project-runbook.md) und [`network-access.md`](network-access.md)
- Letzter abgeschlossener historischer Nachweis: [`system-validation-2026-07-10.md`](system-validation-2026-07-10.md)
- Aktueller Live- und Release-Nachweis: [`system-validation-2026-07-13.md`](system-validation-2026-07-13.md)

## Wie dieses Handbuch zu lesen ist

- **Teil A** ist für Marketing-Anwender und Freigebende geschrieben.
- **Teil B** ist ausschließlich für Administration, Release-Verantwortliche und Incident-Leitung.
- `<KONSOLEN-URL>`, `<N8N-URL>`, `<ADMIN-HOST>` und ähnliche Angaben sind bewusst sichere Platzhalter. Die freigegebenen Werte kommen aus dem internen Passwort-/Konfigurationsspeicher, nicht aus diesem öffentlichen Repository.
- Ein grüner Einzelstatus bedeutet nicht automatisch Betriebsbereitschaft. **Konfiguriert**, **erreichbar**, **erfolgreich benutzt**, **release-qualifiziert** und **produktiv freigegeben** sind unterschiedliche Zustände.

### Inhaltsübersicht

- **Teil A – Marketing-Anwendung:** Rollen und Regeln; fünf Kampagnen; Schnellstart; Tagesablauf; Recherche; KI-/Reel-Content; menschliche Freigabe; K4-Mediengate; Postiz-Entwurf; Ergebnisse; Status; Fehlerhilfe.
- **Teil B – Administration und Betrieb:** aktueller Risikostand; Health-Check; n8n-Sollmanifest; Abhängigkeiten; Backup; Release; Rollback; Incidents; bekannte Grenzen; Abnahmechecklisten; Änderungsverlauf.
- Jede ausführbare Arbeitsanweisung ist mit Verantwortung, Voraussetzungen, Schritten, erwartetem Ergebnis, Stoppbedingungen, Nachweis und Eskalation aufgebaut.

---

## Teil A – Marketing-Anwendung

### 1. Rollen, Verantwortung und nicht verhandelbare Regeln

| Rolle | Darf | Darf nicht |
| --- | --- | --- |
| Marketing-Anwender | Kampagne wählen, öffentliche Quellen recherchieren, redaktionelle Richtungen vergleichen, Entwurf vorbereiten, Messwerte mit Herkunft erfassen | Technische Statuswerte überschreiben, Belege erfinden, Zugangsdaten eingeben, extern veröffentlichen |
| Freigebende Person | Inhalt, Quelle, Marke, Datenschutz und KI-Kennzeichnung prüfen; Freigabe oder konkrete Revision dokumentieren | Sich mit Sammelname anmelden, Prüfungen ohne Durchführung bestätigen, Postiz-Veröffentlichung als Systemfreigabe behandeln |
| Asset-/Einwilligungsverantwortung | Freigegebene Medien und Einwilligungsreferenzen kontrollieren, insbesondere für K4 | Rohdokumente mit personenbezogenen Daten in Content-Feldern oder Repository ablegen |
| Marketing Operations | Wochenplan, Prioritäten, Quellenqualität und Ergebnisfenster steuern | Fehlende Daten als Null oder Erfolg interpretieren |
| IT-/Plattformbetrieb | Identität, TLS, n8n, Modell-, Such- und Publishing-Dienste betreiben; Releases und Rollback verantworten | Inhaltlich freigeben oder Sicherheitsprüfungen durch Konfigurationsflags vortäuschen |

Immer geltende Regeln:

1. Keine öffentliche Veröffentlichung ohne namentliche menschliche Freigabe.
2. Keine Auto-Veröffentlichung durch KI oder n8n.
3. Keine Kunden-, Mitarbeiter-, Bewerber- oder Azubi-Inhalte ohne dokumentierte Einwilligungsreferenz.
4. Keine Statistik, ROI-, Ergebnis-, Sicherheits- oder Compliance-Aussage ohne passenden, für öffentliche Nutzung freigegebenen Beleg.
5. Keine privaten Logins, Bezahlschranken oder Plattformregeln umgehen.
6. Keine Secrets, personenbezogenen Rohdaten oder privaten Beweisdateien in Prompts, Notizen, Screenshots oder Git-Dateien.
7. Eine Freigabe erzeugt höchstens einen Entwurf; die Plattformveröffentlichung bleibt eine zweite menschliche Entscheidung.

### 2. Die fünf echten Kampagnen

Am 13. Juli 2026 sind K1, K2 und K4 zeitlich aktiv. Ihr wirksames Wochenziel beträgt zusammen **9 Inhalte**. K3 und K5 sind geplant und starten am 1. August 2026; bis dahin tragen beide **0** zum wirksamen Wochenziel bei und dürfen nicht als Rückstand erscheinen. Der Status wird aus den hinterlegten Start- und Enddaten berechnet. Nur diese fünf Kampagnen gehören in die normale Anwenderansicht.

| Code | Kampagne | Zielgruppe und Ziel | Primärformat | Konfiguriert | Wirksam am 13.07. | Zentrale Inhaltsgrenze |
| --- | --- | --- | --- | ---: | ---: | --- |
| K1 | Consulting Test- und Qualitätsmanagement | IT-Leiter und QA-Verantwortliche; Interesse an einem QA-Risikoaudit | LinkedIn Expertenbeitrag | 3 | 3 | Ergebnis-, Effizienz- und Entscheidungssicherheitsversprechen nur mit genehmigtem Beleg; ansonsten Prüfen und Priorisieren erklären |
| K2 | KI (Sokrates) | Geschäftsführer und IT-Leiter; Private-KI-Erstgespräch | LinkedIn Carousel | 3 | 3 | Positionierung erklären, aber keine Architektur, Datenhaltung, Sicherheit, DSGVO-Konformität oder Ergebnisse behaupten |
| K3 | LFA – Lernzentrum für Azubis | Schüler, Azubis und Ausbilder; LFA-Demo oder Ausbildungsinformation | Instagram Reel | 5 | 0 – geplant | Keine Personen, Produktoberflächen, Funktionen, Ausbildungsqualität oder Lernergebnisse erfinden |
| K4 | Team & Arbeitgebermarke | Bewerber und B2B-Entscheider; Team kennenlernen | Instagram Reel | 3 | 3 | Reale Medien und Einwilligungen sind Pflicht; keine Kultur, Aussage, Person oder Alltagsszene als Tatsache erfinden |
| K5 | Maßgeschneiderte App-Entwicklung – 50+ Portfolio | IT-Leiter und Geschäftsführer; App-Modernisierungscheck | LinkedIn Portfolio-Carousel | 2 | 0 – geplant | Nur „mehr als 50 Anwendungen in sieben Kategorien“ ohne zusätzliche App-, Liefer- oder Wirkungsaussage verwenden, bis Einzelbelege freigegeben sind |

**Redaktioneller Hinweis:** Zielgruppenprofile liefern Pain Points, Ziele und Entscheidungszusammenhang für die Tonalität. Sie sind keine Quelle für eine öffentliche Tatsachenbehauptung. Kampagnen-Masterprompts sind Arbeitsrichtung, keine automatische Publikationsfreigabe.

### 3. Sicherer Schnellstart

#### Arbeitsanweisung A1 – Konsole öffnen und Arbeitsfreigabe prüfen

**Verantwortlich:** Marketing-Anwender

**Voraussetzungen:** Freigegebener Büroarbeitsplatz; persönliche Zugangsdaten; von IT bestätigte `<KONSOLEN-URL>`; keine Zertifikatswarnung; dokumentierter Betriebsstatus „freigegeben“.

**Schritte:**

1. Öffnen Sie ausschließlich `<KONSOLEN-URL>` aus dem internen Servicekatalog.
2. Prüfen Sie, dass die Adresse mit `https://` beginnt und der Browser keine Zertifikatswarnung zeigt.
3. Prüfen Sie oben in der Konsole Ihre persönliche Identität – kein Sammelname wie „admin“, „marketing“ oder „operator“.
4. Öffnen Sie **Arbeitsfähigkeit**. Dort müssen genau fünf fachliche Möglichkeiten erscheinen: **Recherche**, **Ideen & Texte**, **Medien**, **Freigabe** und **Redaktionsplanung**.
5. Lesen Sie je Möglichkeit den Status **Bereit**, **Prüfung offen** oder **Gesperrt** und den empfohlenen nächsten Schritt. Technische Server-, Modell-, Workflow- und Netzwerkdetails gehören nicht in diese Anwenderansicht.
6. Öffnen Sie **Übersicht** und prüfen Sie, dass ausschließlich K1 bis K5 sichtbar sind.

**Erwartetes Ergebnis:** Verschlüsselte Sitzung, namentlich erkennbare Person, genau fünf verständliche Arbeitsfähigkeiten, fünf Kampagnen und ein klarer nächster Schritt.

**Stoppbedingungen:** HTTP statt HTTPS; Zertifikatswarnung; fehlende oder generische Identität; eine erforderliche Arbeitsfähigkeit ist „Gesperrt“; technische Rohdetails erscheinen in der Anwenderansicht; Demo-/Mock-/Smoke-Inhalte; mehr oder weniger als fünf Kampagnen; wiederholte Ladefehler. Keine Zugangsdaten am HTTP-Endpunkt eingeben.

**Nachweis:** Datum/Uhrzeit, eigener Name, fachlicher Status aus **Arbeitsfähigkeit** und – ohne sensible Inhalte – die betroffene Meldung im Arbeitsticket.

**Eskalation:** Marketing Operations; bei Identitäts-, Zertifikats- oder Sicherheitsproblem sofort IT-/Plattformbetrieb.

> **Aktueller Stopp am 13. Juli 2026:** Diese Voraussetzungen sind im Live-System nicht erfüllt. Der alte HTTP-Endpunkt antwortete beim früheren Audit, beim abschließenden Check war Nvidia-1 jedoch nicht erreichbar. HTTPS und namentliche Konten fehlen. Arbeitsanweisung A1 endet daher bei Schritt 2 beziehungsweise 3.

### 4. Täglicher Marketing-Ablauf

#### Arbeitsanweisung A2 – Tagesstart und Priorisierung

**Verantwortlich:** Marketing Operations oder diensthabender Marketing-Anwender

**Voraussetzungen:** A1 vollständig bestanden; Wochenpriorität bekannt; keine offene Incident-Sperre.

**Schritte:**

1. Öffnen Sie **Übersicht**.
2. Lesen Sie für jede Kampagne Status, wirksames Wochenziel, erreichten Fortschritt, Quellenlage, wartende Freigaben und Blocker. Am 13. Juli sind dies insgesamt 9 Inhalte für K1, K2 und K4; K3 und K5 zählen bis 1. August jeweils 0.
3. Bearbeiten Sie zuerst Sicherheits- oder Quellenblocker, danach wartende Freigaben, dann fehlende Inhalte zum Wochenziel.
4. Öffnen Sie die oberste empfohlene Aufgabe; springen Sie nicht direkt zu einer zufälligen Kampagne.
5. Prüfen Sie am Tagesende fehlgeschlagene Abläufe, neue Leads, fällige Messungen und ungeklärte Postiz-Übergaben.

**Erwartetes Ergebnis:** Eine nachvollziehbare Tagespriorität und keine übersehene Freigabe, Quellenwarnung oder unklare externe Übergabe.

**Stoppbedingungen:** Dashboarddaten widersprechen Kampagnendaten; Wochenzähler enthält alte oder Testinhalte; K3/K5 werden vor ihrem Start als Rückstand gezählt; ein externer Ausgang ist „unklar“; **Arbeitsfähigkeit** meldet eine erforderliche Möglichkeit als gesperrt.

**Nachweis:** Verantwortliche Person und kurze Tagesnotiz mit oberster Aufgabe, Blockern und Übergabe an den nächsten Bearbeiter.

**Eskalation:** Marketing Operations bei Prioritätskonflikten; IT bei Daten-, Dienst- oder Statusabweichungen.

#### Empfohlene Tagesreihenfolge

1. Identität und **Arbeitsfähigkeit** prüfen.
2. Blockierte Quellen oder Einwilligungen lösen.
3. Wartende Freigaben bearbeiten.
4. Fehlende Wocheninhalte recherchieren und erstellen.
5. Postiz-Entwürfe kontrollieren – nur wenn der Integrationsmodus freigegeben ist.
6. Fällige Messfenster mit belegten Daten aktualisieren.
7. Unklare Ausgänge und Incidents dokumentiert übergeben.

### 5. Recherche, Trends und zitierfähige Quellen

#### Arbeitsanweisung A3 – Aktuelle Recherche durchführen

**Verantwortlich:** Marketing-Anwender

**Voraussetzungen:** A1 bestanden; eine der fünf Kampagnen gewählt; Suchziel und Betrachtungszeitraum festgelegt; **Arbeitsfähigkeit** zeigt **Recherche** als bereit.

**Schritte:**

1. Öffnen Sie **Content Studio** und wählen Sie genau eine Kampagne.
2. Starten Sie eine Recherche für die konkrete Aussage oder Fragestellung; der Standardzeitraum für Trendforschung beträgt zehn Tage.
3. Prüfen Sie jeden Treffer auf exakte Themenpassung, Herausgeber, Veröffentlichungsdatum, Abrufzeit und erreichbaren Link.
4. Fordern Sie für einen aktuellen Trend mindestens zwei voneinander unabhängige Domains und mindestens eine datierte, im Zeitraum liegende Quelle.
5. Öffnen Sie die Links selbst. Prüfen Sie, ob die Quelle wirklich die geplante Aussage stützt und nicht nur ein ähnliches Thema behandelt.
6. Verwenden Sie interne Evidenz nur, wenn sie im Evidence Vault für öffentliche Nutzung freigegeben ist. Eine Zielgruppen- oder Kampagnendatei belegt keine externe Marktbehauptung.
7. Übernehmen Sie nur den Trend oder Evergreen-Ansatz, den die Konsole als passend kennzeichnet.

**Erwartetes Ergebnis:** Ein quellenverifizierter Trend mit Titel, Domain, Veröffentlichungsdatum, Abrufdatum, Auszug und Link – oder ein ehrlicher Block ohne Freigabe zur Trendfortsetzung.

**Stoppbedingungen:** Weniger als zwei unabhängige Domains; kein aktuelles Datum; nur ähnliche Aussage; Quelle hinter Login/Paywall nicht prüfbar; Link widerspricht dem Auszug; Quellenstatus nur „erreichbar“ statt „erfolgreich verwendet“; keine aktuelle kampagnenspezifische Recherche.

**Nachweis:** Gespeicherte Research-Run-ID, Quellenliste, Prüfzeit und Name der prüfenden Person. Keine privaten Screenshots oder Anmeldedaten speichern.

**Eskalation:** Marketing Operations bei Themen-/Belegkonflikt; IT bei Adapterfehler, Zeitüberschreitung oder falschem Quellenstatus.

#### Quellenstatus richtig verstehen

| Status | Bedeutung | Erlaubte Verwendung |
| --- | --- | --- |
| `verified_recent` | Exakte Themenpassung, mindestens zwei unabhängige Domains, mindestens eine aktuelle datierte Quelle | Trendbasierte Richtung darf vorbereitet werden; menschliche Faktenprüfung bleibt Pflicht |
| `source_verified_date_unconfirmed` | Mehrere Quellen, aber Aktualität nicht sauber belegt | Nur manuelle Prüfung oder Evergreen; nicht als aktueller Trend ausgeben |
| `single_source_review` | Nur eine externe Quelle | Zweite unabhängige Quelle suchen |
| `evergreen_unverified` | Allgemeine Idee ohne aktuellen Trendnachweis | Als zeitlose Idee kennzeichnen; keine Aktualitätsbehauptung |
| `requires_live_sources` / `needs_live_sources` | Kein erfolgreich verwendeter Live-Adapter | Recherche technisch reparieren; keine Trendbehauptung |
| `needs_source_verification` | Treffer vorhanden, Qualitätsregel nicht erfüllt | Aussage enger formulieren oder besser recherchieren |

**Aktueller Stand:** SearxNG wurde vor dem Verbindungsverlust erfolgreich verwendet; seine aktuelle Erreichbarkeit ist nicht bestätigt. Firecrawl ist weder als lokaler Dienst nachgewiesen noch mit einem Cloud-Schlüssel konfiguriert. Im Produktionsspeicher fehlt weiterhin eine aktuelle freigabefähige Recherche für K1 bis K5. Ein getrennter historischer Kandidatenlauf recherchierte K1 bis K5 über SearxNG und bewahrte neun zitierte Treffer auf; jeder Gegenstand blieb wegen nur einer unabhängigen Quelldomain korrekt `needs_source_verification`. Ein späterer K1-Lauf fand für eine Idee vier unabhängige Domains, aber keine vertrauenswürdige datierte Quelle im Zehn-Tage-Zeitraum und blieb deshalb korrekt `source_verified_date_unconfirmed`. Beide Nachweise belegen sicheres Blockierverhalten, aber keinen aktuellen Trend. Vor jeder aktuellen Trendbehauptung bleiben mindestens zwei unabhängige Domains **und** eine aktuelle datierte Quelle Pflicht.

### 6. KI-Entwurf, Reel-Idee und Content-Paket

#### Arbeitsanweisung A4 – Richtung wählen und vollständigen KI-Entwurf erstellen

**Verantwortlich:** Marketing-Anwender

**Voraussetzungen:** Eine Kampagne ist gewählt; Kampagnenziel und Zielgruppe sind plausibel; für Trendcontent ist A3 bestanden; **Recherche** sowie **Ideen & Texte** sind arbeitsfähig.

**Schritte:**

1. Wählen Sie den verifizierten Recherchegegenstand und ergänzen Sie bei Bedarf einen redaktionellen Wunsch wie „sachlicher“, „Q&A“, „mehr Typografie“ oder „stärkerer Einstieg“.
2. Lassen Sie vier quellenbasierte redaktionelle Richtungen anzeigen. Diese Richtungen werden regelbasiert vorbereitet und sind noch keine vier vollständigen KI-Entwürfe.
3. Vergleichen Sie Idee, Kampagnenformat, Hook, Kernbotschaft, CTA und Quellenbezug der vier Richtungen. Prüfen Sie, ob Zielgruppe, Pain Points und Ziele passen, ohne daraus neue Tatsachen zu erfinden.
4. Wählen Sie genau eine Richtung ausdrücklich aus.
5. Wählen Sie **Mit lokaler KI als Entwurf erstellen**. Erst jetzt erstellt die lokale KI das vollständige Paket im verbindlichen Kampagnenformat – etwa Expertenbeitrag, Carousel oder Reel-Produktionsplan.
6. Prüfen Sie das vollständige Ergebnis: Idee, Format, Hook, öffentlicher Text oder Skript, Szenen-/Produktionsablauf, Visual- oder Edit-Hinweise, Caption, CTA, Hashtags und anklickbare Quellen.
7. Lesen Sie unter **Entstehung** nur den fachlichen Hinweis, ob die lokale KI den Entwurf erfolgreich erstellt hat. Provider, Modellname, Versuchszahl, Latenz, Roh-Hashes und interne IDs werden im Hintergrund für die technische Nachvollziehbarkeit gespeichert, aber nicht in der Anwenderoberfläche angezeigt.
8. Übergeben Sie nur einen erfolgreich erstellten, vollständig geprüften KI-Entwurf zur menschlichen Freigabe.

**Erwartetes Ergebnis:** Ein vollständiges formatgerechtes Content-Paket aus genau einer bewusst gewählten Richtung, mit verständlicher Entstehungsanzeige und überprüfbaren Quellen.

**Stoppbedingungen:** Keine Richtung ausdrücklich gewählt; fehlendes Pflichtfeld; unspezifischer oder fremder Kampagneninhalt; erfundene Person, Oberfläche, Kennzahl oder Kundenaussage; Quellen fehlen; Entstehung nicht bestätigt; lokale KI liefert nur die sichere regelbasierte Arbeitsvorlage; Ergebnis ist gesperrt. Eine solche Vorlage darf niemals zur Freigabe weitergegeben werden.

**Nachweis:** Das System bewahrt gewählte Richtung, Version, Entstehungsnachweis und Quellen im Auditverlauf auf; der Anwender dokumentiert nur die fachliche Entscheidung und öffnet die angegebenen Quellen.

**Eskalation:** Marketing Operations bei Inhaltsqualität; IT bei wiederholtem KI-Fehler, gesperrter Arbeitsvorlage oder unvollständigem strukturiertem Ergebnis.

#### Entstehung und sichere Arbeitsvorlage

| Geschäftliche Anzeige | Interpretation | Handlung |
| --- | --- | --- |
| Mit lokaler KI erstellt | Die lokale KI hat das vollständige strukturierte Ergebnis erfolgreich geliefert | Inhalt und Quellen als Mensch prüfen; KI ist kein Faktenbeleg |
| Sichere Arbeitsvorlage – Erstellung gesperrt | Die regelbasierte Ersatzlogik hat nur eine Orientierung geliefert, keinen freigabefähigen KI-Entwurf | Nicht prüfen, freigeben oder planen; Arbeitsfähigkeit wiederherstellen und neu erzeugen |
| Entstehung nicht bestätigt | Das Ergebnis ist nicht zuverlässig nachvollziehbar | Nicht freigeben; IT informieren |

Die technische Herkunft bleibt im geschützten Auditverlauf erhalten. Die Anwenderoberfläche zeigt bewusst keine Provider-/Modellnamen, Laufzeiten, Roh-Hashes oder internen IDs. Am 13. Juli sind fünf W29-Entwürfe – je einer pro Kampagne – mit bestätigter früherer lokaler KI-Erstellung im Produktionsbestand gespeichert. Zusätzlich erzeugte ein isolierter aktueller Quellkandidat echte lokale Qwen-Entwürfe für K1 bis K5; kontrollierte Revisionen bestanden die deterministische Qualitätsprüfung. Diese Nachweise belegen lokale KI-Erstellung, aber weder sichere Einsatzbereitschaft der Live-Konsole noch menschliche Freigabe, Veröffentlichung oder Produktionsqualifikation. Im Produktionsbestand sind insgesamt elf Nicht-Demo-Contentstände vorhanden; K4 wartet auf Belege.

### 7. Menschliche Prüfung und Freigabe

#### Arbeitsanweisung A5 – Freigeben oder Revision anfordern

**Verantwortlich:** Namentlich identifizierte freigebende Person

**Voraussetzungen:** Persönliche HTTPS-Sitzung; Entwurf im Status `needs_human_review`; vollständiges Content-Paket; alle Quellen erreichbar; keine eigene ungeklärte Interessenkollision.

**Schritte:**

1. Lesen Sie öffentliche Copy, Reel-Ablauf, Caption, CTA, Hashtags und Visual-Anweisung vollständig.
2. Öffnen und prüfen Sie jede verwendete Quelle. Bestätigen Sie nur exakt belegte Aussagen.
3. Prüfen Sie Marke und Ton; ein freigabefähiger Markenfit benötigt mindestens 90 von 100 Punkten.
4. Prüfen Sie Datenschutz und Einwilligungen sowie die Erforderlichkeit einer KI-Kennzeichnung.
5. Tragen Sie Ihren vollständigen Namen und eine kurze, konkrete Prüfnotiz ein. Eine Notiz ist bei Freigabe und Revision Pflicht.
6. Wählen Sie **Überarbeiten**, wenn Hook, Aussage, Quelle, Visual, Ton oder CTA nicht stimmt; beschreiben Sie die Änderung konkret.
7. Wählen Sie **Freigeben** nur, wenn Fakten-, Datenschutz- und KI-Kennzeichnungsprüfung bestanden sind und keine kampagnenspezifische Sperre offen ist.

**Erwartetes Ergebnis:** Auditierbare Freigabe oder versionierte Revision; frühere Versionen und Entscheidungen bleiben erhalten.

**Stoppbedingungen:** Generische oder fehlende Identität; leere Notiz; Markenfit unter 90; eine Pflichtprüfung fehlt; Quelle belegt die Aussage nicht; persönliche Daten oder Medien ohne Einwilligung; K4-Mediengate offen; Entwurf bereits terminal verarbeitet.

**Nachweis:** Content-/Versions-ID, Reviewer, Entscheidung, Markenwert, drei Prüffelder, Notiz und Zeitstempel im Audit-Verlauf.

**Eskalation:** Marketing Operations bei Marke/Beleg; Datenschutzverantwortung bei Personenbezug; IT bei Zustands-, Versions- oder Identitätsfehler.

#### Freigabe ist nicht Veröffentlichung

`approved` beziehungsweise `ready_to_schedule` bedeutet nur, dass der interne Inhalt die festgelegten Prüfungen bestanden hat. Die Freigabe darf höchstens einen Postiz-Entwurf vorbereiten. Terminierung und Veröffentlichung in Postiz oder der Plattform bleiben eine separate menschliche Handlung.

### 8. K4: reales Medium und Einwilligung

#### Arbeitsanweisung A6 – K4-Mediengate erfüllen

**Verantwortlich:** Asset-/Einwilligungsverantwortung; abschließend die freigebende Person

**Voraussetzungen:** K4-Entwurf wartet auf menschliche Prüfung; reales, finales Video liegt vor; dargestellte Personen und Nutzungszwecke sind geklärt; Roh-Einwilligungsdokumente werden außerhalb des Content-Systems geschützt verwaltet.

**Schritte:**

1. Prüfen Sie, dass das Video exakt die zu prüfende Fassung ist und nicht nur ein Platzhalter oder Storyboard.
2. Laden Sie das Video in den freigegebenen Postiz-Entwurf beziehungsweise den vorgesehenen Medienpfad. Kopieren Sie die dort angezeigte Medienreferenz und den Link in die dafür vorgesehenen Felder.
3. Wählen Sie im Freigabeformular exakt dieselbe lokale Originaldatei aus. Der Browser berechnet daraus den unveränderlichen Dateinachweis lokal; die Originaldatei wird dabei nicht an die Marketing-Konsole hochgeladen. Der Dienst liest genau den angegebenen Postiz-Medienpfad und bestätigt im Hintergrund, dass dessen Inhalt mit der lokalen Datei übereinstimmt.
4. Erfassen Sie für jede dargestellte Person eine gültige Einwilligungsreferenz – keine Rohdokumente und keine unnötigen Personendaten.
5. Bestätigen Sie Dateiintegrität, Vorschau, Rechte/Einwilligung und Übereinstimmung mit dem finalen Inhalt.
6. Prüfen Sie die Vorschau erneut und geben Sie den K4-Inhalt erst dann frei. Unmittelbar vor einer späteren Postiz-Entwurfsübergabe prüft das System das Provider-Medium erneut.
7. Bei Ersatz oder Widerruf: Wählen Sie die neue Originaldatei bewusst aus beziehungsweise widerrufen Sie die Freigabe; nie still überschreiben.

**Erwartetes Ergebnis:** Genau ein freigegebenes Video mit Postiz-Referenz, automatisch berechnetem Dateinachweis, Prüfnachweisen und Einwilligungsreferenzen; erst dann kann K4 „Bereit zur Planung“ erreichen.

**Stoppbedingungen:** Fehlende Einwilligung; mehrere aktive Videos; ausgewählte Originaldatei stimmt nicht mit dem Postiz-Medium überein; der direkte Medienpfad ist geändert, umgeleitet, nicht erreichbar oder vom falschen Dateityp; Referenz/Link, Vorschau, prüfende Person, Zeit oder Quelle fehlt; eine der vier Prüfungen ist nicht bestanden; Widerruf; Person im Material ist nicht von der Einwilligung umfasst. Interne Asset-IDs oder Prüfsummen niemals manuell erfinden oder eingeben.

**Nachweis:** Die Konsole speichert Dateibeweis, geschützte Einwilligungsreferenzen, prüfende Person, Zeit, Vorschauentscheidung und Medienverlauf im Hintergrund. Für Anwender bleiben Roh-Hash und interne IDs verborgen.

**Eskalation:** Datenschutz-/Einwilligungsverantwortung sofort; Marketing Operations bei Inhaltswechsel; IT bei Dateinachweis- oder Medienverlaufsfehler.

### 9. Postiz: ausschließlich Entwurfsübergabe

#### Arbeitsanweisung A7 – Freigegebenen Inhalt als Postiz-Entwurf vorbereiten

**Verantwortlich:** Freigebende Person oder Publishing-Verantwortung

**Voraussetzungen:** Fachlicher Status „Bereit zur Planung“; **Redaktionsplanung** ist in **Arbeitsfähigkeit** ausdrücklich bereit; richtige Kanal-Integration ist hinterlegt; bei Visual/Reel ist das genehmigte Medium bestätigt; A1 bestanden.

**Schritte:**

1. Öffnen Sie den freigegebenen Inhalt und prüfen Sie Kanal, Copy, CTA, UTM und Medium erneut.
2. Lesen Sie den angezeigten Modus. **Nur Vorbereitung** verändert Postiz nicht; **externe Entwurfsübergabe bereit** benötigt eine bewusste Bestätigung.
3. Wählen Sie **In Postiz als Entwurf übergeben** genau einmal.
4. Prüfen Sie das Übergabeprotokoll und öffnen Sie den gefundenen Entwurf in Postiz.
5. Prüfen Sie dort Zielkanal, Text, Link, Zuschnitt, Ton, Untertitel, Thumbnail, Zeit und Einwilligungen.
6. Terminieren oder veröffentlichen Sie erst nach der finalen Plattformprüfung durch die zuständige Person.

**Erwartetes Ergebnis:** Eindeutig zugeordneter Postiz-Entwurf; keine automatische Veröffentlichung.

**Stoppbedingungen:** Externe Writes deaktiviert; Vertrag/Integration nicht verifiziert; Postiz-Registrierung offen; falscher Tenant/Kanal; Medium fehlt; Status `delivery_unknown`; Timeout nach Sendeversuch; Anbieter-ID fehlt oder mehrere Treffer. Bei unklarem Ausgang niemals blind erneut senden.

**Nachweis:** Die Konsole speichert den internen Übergabenachweis, Zielkanal, Modus, Zeit und Ergebnis im Hintergrund. Der Anwender prüft nur die verständliche Statusanzeige und – bei eindeutigem Erfolg – den passenden Postiz-Entwurf.

**Eskalation:** IT-/Plattformbetrieb bei technischem oder unklarem Ausgang; Publishing-Verantwortung bei Inhalt/Plattformdarstellung; Datenschutz bei Medienproblem.

#### Übergabestatus

| Status | Bedeutung | Nächste Handlung |
| --- | --- | --- |
| `prepared` | Intern geprüft/protokolliert, keine externe Änderung | Externe Freigabe abwarten |
| `sending` | Übergabe läuft | Nicht erneut klicken; Ergebnis abwarten |
| `sent` | Anbieteraufruf bestätigt, aber noch nicht abschließend abgeglichen | Read-only Abgleich durchführen |
| `delivery_unknown` | Ausgang nach Timeout/Verbindungsfehler unbekannt | Nicht erneut senden; mit Postiz abgleichen und IT informieren |
| `confirmed` / `reconciled` | Genau ein Postiz-Datensatz wurde read-only bestätigt | In Postiz final prüfen; noch nicht automatisch veröffentlicht |
| `failed_safe_to_retry` | Anbieter hat eindeutig nicht erstellt | Erst Ursache beheben; kontrollierter Retry durch zuständige Person |
| `blocked` | Governance- oder Konfigurationssperre | Sperrgrund lösen; nicht umgehen |

> **Aktueller Stand:** Externe Schreibvorgänge sind deaktiviert und Postiz ist nicht release-qualifiziert; die Live-Registrierung ist zudem offen. A7 darf deshalb derzeit keinen externen Entwurf erzeugen.

### 10. Ergebnisse und Messfenster

#### Arbeitsanweisung A8 – Messwerte mit Herkunft erfassen

**Verantwortlich:** Marketing Operations oder Analytics-Verantwortung

**Voraussetzungen:** Provider-bestätigte Veröffentlichung; Messfenster 72 Stunden, 7 Tage, 14 Tage oder 30 Tage ist fällig; überprüfbarer Plattformexport oder Bericht liegt vor.

**Schritte:**

1. Öffnen Sie **Ergebnisse** und wählen Sie eine fällige Aufgabe unter **Heute messen**.
2. Übertragen Sie nur tatsächlich berichtete Zählwerte; fehlend ist nicht null.
3. Aktivieren Sie für jede verwendete Kennzahlengruppe den passenden Quellenbeleg und wählen Sie die exakte Exportdatei aus. Der Browser berechnet den unveränderlichen Dateinachweis automatisch und lokal; die Exportdatei wird nicht an die Konsole hochgeladen.
4. Erfassen Sie Quellenreferenz, Beginn und Ende des Messzeitraums, Abrufzeit, Ihren Namen und die angewendete Zuordnungsregel.
5. Prüfen Sie Plausibilität: qualifizierte Leads dürfen nicht über allen Leads liegen; Gespräche nicht über qualifizierten Leads; Landingpage-Abschlüsse nicht über Besuchen.
6. Dokumentieren Sie die Entscheidung: warten, iterieren, Landingpage verbessern, Zielgruppe/Angebot korrigieren, skalieren oder stoppen.
7. Korrigieren Sie Fehler append-only; überschreiben Sie den früheren Nachweis nicht still.

**Erwartetes Ergebnis:** Nachvollziehbarer Messdatensatz mit Zeitfenster, Herkunft und Entscheidung; keine erfundenen oder vorzeitigen Kennzahlen.

**Stoppbedingungen:** Veröffentlichung nicht bestätigt; Fenster noch nicht fällig; Quellenbeleg oder exakte Exportdatei für eine verwendete Kennzahlengruppe fehlt; widersprüchliche Werte; Wiederholung widerspricht vorhandenen Daten; automatische Plattformaufnahme wird nur vermutet.

**Nachweis:** Die Konsole speichert Veröffentlichungsbezug, Messfenster, Export-/Berichtsreferenz, automatischen Dateinachweis, Abrufzeit, verantwortliche Person, Zuordnungsregel und Entscheidung. Roh-Hash und interne IDs bleiben in der Anwenderoberfläche verborgen.

**Eskalation:** Marketing Operations bei fachlicher Abweichung; IT bei fehlender Aufgabe, Status- oder Validierungsfehler; Plattformverantwortung bei Exportdifferenz.

#### Entscheidungsrhythmus

| Zeitpunkt | Fokus | Keine voreilige Interpretation |
| --- | --- | --- |
| 72 Stunden | Frühe Signale: Saves, Kommentare, Profilbesuche, CTR, Landingpage-Klicks | Noch keine belastbare Geschäftsentscheidung erzwingen |
| 7 Tage | Hook, Format, CTA, Thumbnail und erste Zeile | Nur eine Testvariable gleichzeitig ändern |
| 14 Tage | Message-Market-Fit, Angebot, Landingpage, Zielgruppe | Ohne nützliches Zielgruppensignal iterieren oder stoppen |
| 30 Tage | Qualifizierte Leads, Gespräche, Pipelinewert | Reichweite allein ist kein Skalierungsgrund |

Die Plattform-Metrikaufnahme ist noch nicht vollständig automatisiert. n8n entdeckt fällige Fenster read-only; es ersetzt weder den Providerexport noch die menschliche Zuordnung.

### 11. Statusglossar

#### Content-Status

| Technischer Status | Anzeige für Marketing | Bedeutung / nächste Aktion |
| --- | --- | --- |
| `drafting` | Entwurf wird erstellt | Generierung abschließen und Pflichtfelder prüfen |
| `needs_evidence` | Beleg fehlt | Passenden öffentlichen oder intern freigegebenen Beleg ergänzen |
| `needs_human_review` | Freigabe wartet | A5 durchführen; bei K4 vorher A6 |
| `revision_requested` | Überarbeitung angefordert | Konkrete Notiz umsetzen und neue Version erzeugen |
| `approved` | Inhaltlich freigegeben | Technische Scheduler-/Medienbedingungen prüfen |
| `ready_to_schedule` | Bereit zur Planung | Höchstens Postiz-Entwurf nach A7 vorbereiten |
| `scheduled` | Terminiert | Plattformvorschau und Termin überwachen |
| `published` | Provider-bestätigt veröffentlicht | Messfenster starten |
| `blocked` | Gesperrt | Grund beheben; nicht manuell umgehen |

#### Dienst- und Release-Status

| Begriff | Genaue Bedeutung |
| --- | --- |
| Konfiguriert | Eine URL oder Einstellung ist vorhanden; kein Funktionsnachweis |
| Erreichbar | Netzwerkantwort ist möglich; Vertrag, Modell oder Berechtigung kann trotzdem falsch sein |
| Erfolgreich verwendet | Ein echter, begrenzter Lauf wurde protokolliert |
| Release-qualifiziert | Exakter Vertrag, Identität, Fehlerpfade, Beweise und Rollback wurden geprüft |
| Produktiv freigegeben | Alle Pflichtgates bestanden, Change genehmigt und nach Deployment abgenommen |
| Degradiert | Teilfunktion verfügbar, aber ein erforderlicher Pfad ist gestört |
| Blockiert | Sicherer Betrieb ist nicht zulässig; keine Umgehung |

#### Fünf Arbeitsfähigkeiten für Marketing

| Fachliche Möglichkeit | Was die Anzeige beantwortet |
| --- | --- |
| Recherche | Können aktuelle öffentliche Quellen jetzt sicher recherchiert und belegt werden? |
| Ideen & Texte | Kann aus einer gewählten Richtung jetzt ein vollständiger lokaler KI-Entwurf entstehen? |
| Medien | Kann das exakte Originalmedium mit Vorschau, Rechten und Einwilligungen belegt werden? |
| Freigabe | Kann eine namentliche Person den vollständigen Entwurf jetzt sicher prüfen und freigeben? |
| Redaktionsplanung | Kann ein freigegebener Inhalt höchstens als Entwurf an den geprüften Redaktionsweg übergeben werden? |

Jede Karte zeigt nur **Bereit**, **Prüfung offen** oder **Gesperrt** sowie den nächsten fachlichen Schritt. Technische Details bleiben bei der Administration.

### 12. Fehlerhilfe für Marketing-Anwender

#### Arbeitsanweisung A9 – Problem sicher eingrenzen

**Verantwortlich:** Marketing-Anwender; Marketing Operations koordiniert

**Voraussetzungen:** Fehler reproduzierbar oder Meldung sichtbar; keine Zugangsdaten/privaten Daten im Ticket.

**Schritte:**

1. Stoppen Sie die aktuelle Aktion und klicken Sie nicht mehrfach.
2. Notieren Sie Uhrzeit, Bereich, Kampagne, sichtbaren Titel/Stand, Status und letzte sichere Aktion. Interne IDs müssen Sie nicht suchen oder abschreiben.
3. Prüfen Sie in der Tabelle unten die erlaubte Selbsthilfe.
4. Aktualisieren Sie die Seite höchstens einmal, wenn kein Sendevorgang lief.
5. Dokumentieren Sie Fehlermeldung und erwartetes Ergebnis; schwärzen Sie personenbezogene oder geheime Werte.
6. Eskalieren Sie an die genannte Stelle und warten Sie bei Sicherheits-/Übergabefehlern auf Freigabe.

**Erwartetes Ergebnis:** Reproduzierbarer, datenschutzkonformer Fehlerbericht ohne Doppelübertragung oder Statusmanipulation.

**Stoppbedingungen:** Unklarer externer Ausgang; Identitätswechsel; Zertifikatswarnung; HTTP; Datenverlustverdacht; falscher Tenant/Kanal; personenbezogene Daten sichtbar; mehrfacher Fehler.

**Nachweis:** Zeit, eigener Name, Bereich, Kampagne, sichtbarer Titel/Stand, Status, Fehlermeldung, letzter Schritt und – falls sicher – bereinigter Screenshot.

**Eskalation:** Nach Tabelle; bei Zweifel IT-/Plattformbetrieb und Marketing Operations gemeinsam.

| Symptom | Erlaubte Selbsthilfe | Stoppen und eskalieren, wenn |
| --- | --- | --- |
| Keine verifizierten Quellen | Suchfrage enger formulieren, Zeitraum und exakte Aussage prüfen, neu recherchieren | Adapterfehler, keine aktuelle Quelle oder wiederholt falsche Themenpassung |
| Nur eine Domain / kein Datum | Zweite unabhängige, datierte Quelle suchen | Aussage dennoch als Trend erscheinen soll |
| Kein vollständiger Entwurf | **Arbeitsfähigkeit** prüfen und nach Wiederherstellung aus der gewählten Richtung neu erzeugen | Erneute Erstellung fehlschlägt oder Entstehung nicht bestätigt wird |
| Sichere Arbeitsvorlage angezeigt | Nicht freigeben; nach Wiederherstellung der lokalen KI neu erzeugen | Die Vorlage als prüf-, freigabe- oder planbar erscheint |
| Freigabe gesperrt | Pflichtfelder, Quellen, Notiz, Markenfit und Checks prüfen | Status/Version widersprüchlich ist |
| K4 bleibt gesperrt | A6 vollständig prüfen | Einwilligung oder exaktes Video nicht eindeutig ist |
| Postiz-Ausgang unklar | Read-only Abgleich wählen | Kein eindeutiger Treffer; niemals erneut senden |
| Messwerte fehlen | Providerexport beschaffen | Veröffentlichung nicht bestätigt oder Quelle fehlt |
| Arbeitsfähigkeit „Bereit“, Funktion scheitert | Fehler dokumentieren | Status und tatsächliches Verhalten widersprüchlich bleiben |
| Zertifikats-/Loginproblem | Keine Umgehung | Immer sofort |

---

## Teil B – Administration und Betrieb

### 13. Aktueller Umgebungs- und Risikostand

Die folgende Tabelle trennt die schreibgeschützte Live-Inventur vom 13. Juli 2026 ausdrücklich von lokalen und isolierten Kandidatennachweisen. Es wurden dabei keine Remote-Schreibvorgänge ausgeführt.

| Bereich | Festgestellter Istzustand | Freigabeauswirkung |
| --- | --- | --- |
| Nvidia-1 | Beim früheren Audit intern erreichbar mit etwa 2,3 TB freiem Datenträger und 98 GiB freiem RAM; beim abschließenden Bürocheck nicht mehr auflösbar oder per SSH erreichbar | **Blocker:** aktuellen Zustand und alle Produktionspfade nach stabiler Verbindungswiederherstellung erneut attestieren |
| Produktionskonsole | Beim früheren Audit antwortete HTTP-LAN `:18117`; HTTPS scheiterte; `/session` lieferte 404; HSTS, CSP und X-Frame-Options fehlten. Aktuelle Erreichbarkeit nicht bestätigt | **Blocker:** keine sichere Operatornutzung, keine aktuelle Freigabe |
| Produktionsimage | Älteres Image mit Digest-Präfix `sha256:a5442c…` | Nicht der gehärtete Kandidat |
| Alter Kandidat | Loopback `:18118`, Digest-Präfix `sha256:1c7a6d…`; Sicherheitsdrift zum Default-Root erkannt | Neu bauen und vollständig neu qualifizieren |
| Lokaler gehärteter Prüfstand | Vollständige Regression mit 452 erfassten Tests: 450 bestanden und 2 übersprungen; Ruff, mypy, Abhängigkeits- und Konfigurationsprüfungen grün; authentifizierte Operator- und sichere Degradationsabläufe auf Desktop/Mobil bestanden; null WCAG-A/AA-Verstöße | Abschließende UI-Evidenz für den isolierten Kandidaten, aber keine Produktions-, TLS-, Nvidia- oder Abhängigkeitsfreigabe |
| Lokale Plattformimages | Exakte aktuelle amd64-Identität `sha256:0ae6c4c57d2564f83929aec844bb54be5e6bca297c1b6efc00b38074478929f8` und arm64-Identität `sha256:7527599ee25d47a9475f60df763e479ce62de205cd8dd7d89737f712c5068d70`; jeweils 97 Pakete und Docker Scout 0 kritisch/0 hoch/0 mittel/0 niedrig; SPDX-SBOMs neu erzeugt; beide lokal mit schreibgeschütztem Dateisystem, UID/GID `10001`, `no-new-privileges`, Authentifizierungsablehnung 401 sowie genau K1 bis K5 ohne Demos bestanden | Arm64 lief über QEMU und meldete `aarch64`, nicht auf echter Nvidia-Hardware. Die Identitäten belegen den aktuellen lokalen Quellstand; nach jeder relevanten Änderung Images/SBOMs neu bauen und betroffene Prüfungen wiederholen. Keine Produktionsfreigabe ableiten |
| Mutationen | Externe Writes sind `false` | Korrekte sichere Sperre; beibehalten |
| Live-Contentdaten, zuletzt beobachtet | Genau K1 bis K5; elf Nicht-Demo-Zustände; fünf W29-Entwürfe mit lokaler-Qwen-Provenienz; K4 braucht Belege | Nicht mit isolierten Kandidaten-/Evaluatorläufen verwechseln; Daten erhalten, frisch sichern und keine Green-Aussage ableiten |
| Trenddaten in Produktion | Nur QA-/Testläufe, keine aktuelle freigabefähige K1-bis-K5-Recherche | Keine aktuelle Trendaussage zulässig |
| Isolierte Recherche | Historischer K1-bis-K5-Lauf: neun zitierte Treffer, je Gegenstand eine Domain. Neuester K1-Lauf: vier Domains für eine Idee, aber null vertrauenswürdige datierte Quellen im Zeitraum | Beide Ergebnisse korrekt blockiert; für Grün sind je Gegenstand zwei unabhängige Domains und eine aktuelle datierte Quelle nötig |
| n8n Edge | LAN `:15678` liefert 502; Proxy hält veraltete Container-IP | **Blocker:** Proxy-/Namensauflösung korrigieren und neu prüfen |
| n8n Runtime | Zuletzt live Version 2.29.10 mit anderem Digest; 13 Workflows, davon 11 aktiv und 2 inaktiv. Der geprüfte Migrationskandidat pinnt dagegen 2.29.9 (`e0d959…`) | **Blocker:** eine exakte Version/Digest freigeben; Tombstone fälschlich aktiv, Retention-Workflow fehlt, Wahrheitsflags falsch |
| TLS/Identität | CA, Zertifikat, Schlüssel, htpasswd, namentliche Konten und read-only n8n-API-Key fehlen | **Blocker:** Material sicher bereitstellen, Rechte und persönliche Konten prüfen |
| Lokale KI | Vor dem Verbindungsverlust erzeugte ein isolierter Kandidat über Qwen auf Nvidia-2 echte strukturierte K1-bis-K5-Entwürfe und bestand kontrollierte Qualitätsrevisionen; aktuell nicht erreichbar | Historische Provenienz bewahren; Verbindung, echte Nvidia-ARM64-Ausführung und Abhängigkeitspfad am exakten finalen Artefakt erneut prüfen. Lokales QEMU ersetzt diese Abnahme nicht |
| ComfyUI | Isolierter Nvidia-2-FLUX-Kandidat hat einen echten API-Lauf mit strikt dekodiertem 512×512-Ergebnis und gebundenen Modell-/Runtime-/Workflow-Hashes bestanden; Produktion blieb unverändert | **Technisch qualifiziert, aber nicht release-freigegeben:** namentliche Sichtentscheidung und Lizenzbestätigung fehlen |
| SearxNG | Vor dem Verbindungsverlust erfolgreich verwendet; aktuelle Erreichbarkeit nicht bestätigt | Adapterfunktion historisch belegt; jüngster K1-Lauf bestand die Domain-, aber nicht die Datumsgrenze und ist nicht freigabefähig |
| Firecrawl | Kein lokaler Dienst nachgewiesen; Cloud-Key fehlt | Optionaler Adapter nicht verfügbar; nicht als aktiv anzeigen |
| Postiz | Vertrag/Credentials nicht release-qualifiziert; Registrierung offen | **Sicherheitsblocker für externe Übergabe** |
| Twenty | Version 2.20.0 aus mutable `latest`; Drift zur Sollfassung | Keine Produktionswrites; unveränderlichen Digest qualifizieren |
| Mautic | Installer endet HTTP 500 | Nicht betriebsbereit; keine CRM-Integration aktivieren |
| Observability | Prometheus/Grafana gestoppt | Betriebsüberwachung unvollständig |
| Kimi-Cloudroute | Credential lokal konfiguriert; externe Rotation/Neuausgabe und erneute Qualifikation fehlen | **Blocker für Cloudnutzung:** beim Anbieter rotieren oder neu ausgeben; Fallback bis danach deaktiviert lassen |
| GitHub-Repository | Öffentlich; für `main` ist keine Branch-Protection beziehungsweise kein Ruleset aktiv | **Release-Governance-Blocker:** nur Pull Request, Pflicht-CI, namentliches Review und kein direkter/Force-Push |
| Browserbilder | Aktuelle Desktop-/Mobilbilder nach den UI-Korrekturen; authentifizierte Operatorabläufe und sicherer Degradationspfad bestanden | Finale UI-Evidenz für den geprüften isolierten Kandidaten; kein Beleg für Produktion, TLS oder einen erfolgreichen abhängigkeitsgestützten aktuellen Trendlauf |
| Release-Archiv | Das finale lokale Quellarchiv für diesen dokumentierten Stand enthält 190 gesteuerte Quelldateien plus eingebettetes Inventar; externer Hash und Inventar stimmen, Pflichtdateien sind vorhanden, verbotene Laufzeit-/Secret-/Git-/Cache-/QA-Pfade fehlen und Gitleaks meldet keine Funde | Lokales Packaging-Gate bestanden. Die maßgebliche Identität steht nur in den externen Sidecars unter `qa_output/release/`, nicht selbstbezüglich in diesem Handbuch. Exakt dieses Archiv genehmigt übertragen, Zielhash prüfen und isoliert auf Nvidia bauen; jede spätere gesteuerte Änderung macht es ungültig |
| Backup | Backup vom 10. Juli: 980.954.960 Bytes; 29/29 Prüfsummen gültig; nach neuen Entwürfen veraltet | Frisches, verschlüsselbares Pre-Change-Backup erforderlich; Restoreprobe bleibt nötig |

#### Sichere Adresskonvention

| Platzhalter | Bedeutung |
| --- | --- |
| `<KONSOLEN-URL>` | Freigegebener HTTPS-LAN-Endpunkt der Marketing-Konsole |
| `<N8N-URL>` | Freigegebener HTTPS-LAN-Endpunkt für n8n-Administration |
| `<ADMIN-HOST>` | Interner Nvidia-1-Hostname aus dem geschützten Servicekatalog |
| `<PROJECT_ROOT>` | Projektpfad aus dem geschützten Servicekatalog; das öffentliche Runbook enthält nur den Platzhalter |
| `<BACKUP_ROOT>` | Geschützter Backup-Pfad außerhalb des Git-Repositories |
| `<CHANGE_ID>` | Genehmigte Change-/Wartungsfenster-ID |

Interne IP-Adressen, Benutzernamen und konkrete URL-Werte gehören in den geschützten Servicekatalog beziehungsweise das Change-Ticket, nicht in diese öffentliche Dokumentation.

### 14. Technischer Gesundheitscheck

#### Arbeitsanweisung B1 – Read-only Preflight durchführen

**Verantwortlich:** Primärer IT-/Plattformoperator; sekundärer Operator kontrolliert

**Voraussetzungen:** Genehmigtes Change-/Prüfticket; persönliche SSH-Identität; verifizierter Host-Key; keine geplante Mutation; geschützter Zugriff auf Servicekatalog; sekundärer Operator informiert.

**Schritte:**

1. Prüfen Sie Host, Uhrzeit, Uptime, Datenträger, RAM und Dockerzustand read-only.
2. Inventarisieren Sie Container, Images, Bindings, Netzwerke und Health-Status ohne Neustart.
3. Prüfen Sie Produktions- und Kandidatenendpunkte getrennt: HTTP, HTTPS, `/session`, `/healthz`, `/readyz` und Sicherheitsheader.
4. Prüfen Sie, dass Raw-Ports nur an Loopback gebunden sind und LAN-Zugriff ausschließlich über den geschützten Proxy erfolgt.
5. Prüfen Sie externe Schreibflags, Mutationsauthentifizierung und Actor-Attestation. Secrets nur auf Existenz, Eigentümer, Modus und Mindestlänge prüfen; niemals ausgeben.
6. Prüfen Sie Qwen, SearxNG, Firecrawl, ComfyUI, Postiz, Twenty, Mautic und Observability getrennt nach konfiguriert, erreichbar, erfolgreich verwendet und release-qualifiziert.
7. Prüfen Sie n8n read-only gegen das exakte Manifest aus Abschnitt 15.
8. Prüfen Sie Backupmanifest und Archivhash; führen Sie keine produktive Änderung aus.

**Erwartetes Ergebnis:** Datiertes, sanitisiertes Istbild mit klaren Pass/Fail-Gates und ohne Systemänderung.

**Stoppbedingungen:** Host-Key ändert sich; Zielhost unklar; Befehl würde schreiben/restarten; Secret könnte ausgegeben werden; Datenpfad oder Volume nicht eindeutig; Proxy zeigt auf unerwarteten Tenant/Container; Backupintegrität fehlerhaft.

**Nachweis:** Change-ID, Operatoren, Start/Ende, Host-Fingerprintreferenz, Container-/Image-Digests, Endpointstatus, Header, n8n-Manifestvergleich, Backuphashstatus und Ressourcenwerte – sanitisiert.

**Eskalation:** Incident-Leitung bei Sicherheits-/Datenverdacht; Service Owner bei Drift; Change-Verantwortung bei jedem Blocker.

#### Minimale Admin-Ampel

| Ampel | Bedingung |
| --- | --- |
| Grün | Sämtliche Release-Gates bestanden, exakte Artefakte identifiziert, Rollback verfügbar, keine offene Hoch-/Mittelabweichung |
| Gelb | Nichtkritische Teilfunktion degradiert, Kernbetrieb sicher und explizit freigegeben; Einschränkung sichtbar dokumentiert |
| Rot | TLS/Identität, Mutation, Datenintegrität, n8n-Manifest, kritische Abhängigkeit, Backup oder Rollback nicht nachgewiesen |

Der aktuelle Livezustand ist **rot**.

### 15. Exaktes n8n-Manifest

Der maschinenlesbare Sollzustand steht in [`scripts/release_acceptance.py`](../scripts/release_acceptance.py). Ein Workflow muss mit der stabilen ID **genau einmal** vorkommen und exakt den angegebenen Aktivzustand besitzen. Dateiflag und Umgebungsvariable sind keine Live-Beweise; maßgeblich ist die read-only n8n-API nach Import, Credential-Bindung, Publikation und Neustart.

#### Muss genau einmal aktiv sein

| Zweck | Stabile ID | Versionierte Datei |
| --- | --- | --- |
| Manuelle Content-Aufnahme | `lYfpV4r4oeEzPtuO` | `manual-content-intake.json` |
| Integrationsgesundheit | `Psaft2cYujD42MAs` | `integration-health.json` |
| Wöchentliche Planung | `GqGVw06F64o7rvjI` | `weekly-planning.json` |
| Verifizierte Trendrecherche | `WMCTrendResearch01` | `trend-research-intake.json` |
| Analytics-Fälligkeit 72 Stunden | `eTZSmmzKe6dJ1knR` | `analytics-72h.json` |
| Analytics-Fälligkeit 7 Tage | `WMCAnalytics7d01` | `analytics-7d.json` |
| Analytics-Fälligkeit 14 Tage | `WMCAnalytics14d1` | `analytics-14d.json` |
| Analytics-Fälligkeit 30 Tage | `WMCAnalytics30d1` | `analytics-30d.json` |

#### Muss genau einmal inaktiv sein

| Zweck | Stabile ID | Begründung |
| --- | --- | --- |
| Ehemaliger Shared-Token-Freigabewebhook | `5OzpL9oBMR8gpSJA` | Freigabe gehört ausschließlich in die authentifizierte Konsole |
| Gestaffelte lokale Lead-Anonymisierung | `WMCLeadRetention01` | Separater, noch nicht freigegebener Datenschutz-Release |

**Zuletzt beobachtete Live-Abweichung am 13. Juli:** Der Freigabe-Tombstone war fälschlich aktiv; `WMCLeadRetention01` fehlte; Verifikations-Umgebungswerte behaupteten fälschlich Erfüllung. Der n8n-LAN-Proxy lieferte zudem 502 wegen einer veralteten gecachten Containeradresse. Live lief n8n 2.29.10 mit einem anderen Digest als der geprüfte 2.29.9-Migrationskandidat. Wegen des späteren Verbindungsverlusts ist auch dieser Zustand nicht aktuell re-attestiert und darf nicht als verifiziert angezeigt werden.

### 16. n8n korrigieren und abnehmen

#### Arbeitsanweisung B2 – Versionierten Workflowbestand ausrollen

**Verantwortlich:** n8n-Service-Owner; sekundärer Operator kontrolliert; Business Approver bestätigt Freigabegrenze

**Voraussetzungen:** Frisches Pre-Change-Backup inklusive n8n-Datenbank, Workflows, Credentials, Konfiguration und Verschlüsselungsmaterial; geprüfter Restoreweg; exaktes Release-Archiv/Hash; Wartungsfenster; persönliche n8n-Konten; read-only API-Key; Rollbackowner.

**Schritte:**

1. Erfassen Sie den aktuellen Livebestand und exportieren Sie ihn read-only beziehungsweise über den freigegebenen Backupweg.
2. Beheben Sie die Proxyauflösung über Servicenamen/DNS entsprechend dem Runbook; keine feste flüchtige Container-IP hinterlegen.
3. Importieren Sie ausschließlich die versionierten Workflowdateien und binden Sie die vorgesehenen minimal berechtigten Credentials.
4. Publizieren Sie die acht aktiven Workflows; setzen Sie die zwei inaktiven Einträge explizit inaktiv.
5. Entfernen Sie keine fremden Workflows ohne eigene Freigabe. Prüfen Sie Dubletten anhand der stabilen ID.
6. Starten Sie nur den für diese Release-Schicht vorgesehenen Dienst neu.
7. Rufen Sie mit dem read-only API-Key den gesamten paginierten Workflowbestand ab und vergleichen Sie ihn maschinell mit Abschnitt 15.
8. Führen Sie genau einen idempotenten, begrenzten Test pro freigegebenem Intake und die read-only Fälligkeitsprüfungen aus. Die menschliche Freigabe bleibt in der Konsole.
9. Setzen Sie Verifikationsflags erst nach bestandenem Live-Nachweis; nie vorab.

**Erwartetes Ergebnis:** Acht IDs genau einmal aktiv, zwei IDs genau einmal inaktiv, keine Dubletten, Proxy gesund, Credentials korrekt gebunden und keine ungeplante externe Mutation.

**Stoppbedingungen:** Backup/Encryption-Material unvollständig; Import erzeugt neue statt stabiler IDs; Credential fehlt oder ist zu weit berechtigt; Tombstone aktiv; Retention aktiv; Proxy weiter 502; API-Paginierung unvollständig; Test erzeugt unerwartete externe Änderung.

**Nachweis:** Vor-/Nach-Export, Manifestvergleich, Credential-Namen ohne Werte, n8n-Version, Aktivstatus, Testausführungs-IDs, Proxyhealth, Operatoren, Zeiten und Change-ID.

**Eskalation:** n8n-Service-Owner und Change-Leitung; bei Daten-/Credentialproblem Incident-Leitung und Security.

### 17. Abhängigkeiten und Freigabegrenzen

| Dienst | Zweck | Aktueller Status | Bedingung für Grün |
| --- | --- | --- | --- |
| Local Qwen | Strukturierte deutsche Content-Entwürfe | Vor dem Verbindungsverlust erfolgreich benutzt; isolierter Kandidat erzeugte echte K1-bis-K5-Entwürfe mit Provenienz und kontrollierter Qualitätsprüfung | Verbindung wiederherstellen; sichere Konsole, korrekte Modellroute und Nachweis am exakten finalen Artefakt auf echter Nvidia-ARM64-Hardware prüfen; lokales QEMU genügt nicht |
| SearxNG | Öffentliche Webrecherche | Vor dem Verbindungsverlust erfolgreich benutzt. Historischer K1-bis-K5-Lauf: neun Single-Source-Treffer. Neuester K1-Lauf: vier Domains, aber null vertrauenswürdige datierte Quellen | Mindestens zwei unabhängige Domains und eine aktuelle datierte Quelle je freigegebenem Gegenstand; aktuelle Blocker nicht als Trends umdeuten |
| Firecrawl | Optionales Extrahieren/Recherche | Nicht verfügbar | Privater geprüfter Dienst oder geschützter Cloud-Key; realer begrenzter Lauf |
| ComfyUI | Governed Creative/Visuals | Isolierter Kandidat technisch qualifiziert; nicht produktiv freigegeben | Namentliche Sichtentscheidung und Lizenzbestätigung an exakt gebundener Ausgabe; danach separater kontrollierter Creative-Release |
| Postiz | Draft-only Publishing-Handoff | Nicht release-qualifiziert; offene Registrierung | Registrierung schließen; Tenant, Credential, Integration-ID, Vertrag, Idempotenz, Cleanup und Stagingbeweis |
| Twenty | CRM-Ziel | Mutable `latest`/Versionsdrift | Unveränderlicher Digest, minimales Rollenmodell, Workspace-Vertrag, reversible Stagingprüfung |
| Mautic | Marketing Automation | Installer 500 | Repariertes gepinntes Kandidatenimage, abgeschlossene Installation, OAuth-/Feldvertrag, reversible Stagingprüfung |
| Prometheus/Grafana | Überwachung | Gestoppt | Authentifizierte Dienste, Metrik- und Dashboardnachweis, Alerts mit Owner |
| Kimi | Optionaler Cloud-Fallback | Credential konfiguriert, aber externe Rotation/Neuausgabe und erneute Qualifikation fehlen | Beim Anbieter rotieren oder neu ausgeben, Route anschließend separat qualifizieren; bis dahin deaktiviert |

**ComfyUI-Prüfregel:** Für den isolierten FLUX-Schnell-Kandidaten gelten die SHA-256-Werte der tatsächlich heruntergeladenen Dateien. Hugging-Face-Xet-CAS-Identifikatoren werden getrennt und nur informativ gespeichert; sie dürfen niemals als Datei-Prüfsumme verwendet werden. Der offizielle Encodervertrag ist positionsgebunden: `clip_name1=t5xxl_fp8_e4m3fn.safetensors` und `clip_name2=clip_l.safetensors`. Am 13. Juli bestand ein loopback-gebundener Kandidat einen echten API-Job; das 512×512-RGB-Ergebnis wurde vollständig dekodiert und an Prompt-, Workflow-, Runtime- und Modell-Hashes gebunden. Dieser technische Nachweis ist keine Produktivfreigabe. Erforderlich bleiben die namentliche Sichtentscheidung am exakt gebundenen Bild und die dokumentierte Lizenzbestätigung.

#### Arbeitsanweisung B3 – Kritische Abhängigkeit qualifizieren

**Verantwortlich:** Eigentümer der jeweiligen Integration; Security/Datenschutz bei externen oder personenbezogenen Pfaden

**Voraussetzungen:** Isolierte Staging-/Kandidatenumgebung; gepinnte Version/Digest; minimal berechtigtes Secret aus sicherem Store; dokumentierter Vertrag; Testdaten ohne echte Personen; Cleanup- und Rollbackplan.

**Schritte:**

1. Inventarisieren Sie Version, Digest, Netzwerkgrenze, Authentifizierung und Health-Vertrag.
2. Prüfen Sie lesend, dass Zieltenant, Modell oder Workspace exakt stimmt.
3. Führen Sie einen begrenzten synthetischen Test mit Idempotency-Key aus.
4. Prüfen Sie Erfolg, Timeout, 4xx, 5xx, Rate Limit, unklaren Ausgang und Wiederanlauf.
5. Löschen beziehungsweise anonymisieren Sie synthetische Testdaten und weisen Sie das Cleanup nach.
6. Speichern Sie sanitisierten Request-/Response-Vertrag, IDs, Zeit, Version und Prüfer im Evidence Vault/Change-Ticket.
7. Aktivieren Sie den Produktionspfad erst in einem separaten genehmigten Release.

**Erwartetes Ergebnis:** Reproduzierbare, reversible Qualifikation mit wahrer Health-Anzeige und klarer Fehlerbehandlung.

**Stoppbedingungen:** Mutable Tag; offene Registrierung; Admin-Credential statt Minimalrolle; Zieltenant unklar; reale Personendaten; nicht reversibler Test; unklarer Ausgang ohne Reconciliation; Versions-/Vertragsdrift.

**Nachweis:** Digest/Version, Vertragshash, Test-ID, Idempotency-Key-Referenz, Zeit, Operator, Ergebnis, Cleanup und Rollbacknachweis – ohne Secretwerte.

**Eskalation:** Service Owner; Security/Datenschutz bei Identitäts- oder Datenrisiko; Change-Leitung bei jedem fehlgeschlagenen Gate.

### 18. Backup, Release und Rollback

#### Arbeitsanweisung B4 – Frisches Pre-Change-Backup erstellen und prüfen

**Verantwortlich:** Backup-/Rollbackowner; sekundärer Operator kontrolliert

**Voraussetzungen:** Wartungsfenster vorbereitet; vollständige Daten- und Volumeliste; ausreichend Speicher; Verschlüsselungsmaterial geschützt verfügbar; keine laufende Schema-/Workflowänderung.

**Schritte:**

1. Erfassen Sie Produktionsimage, Compose-/Env-Konfiguration, Runtime-Daten, n8n-Datenbank, Workflowexport, Credentials, Encryption-Material sowie relevante Postiz-/CRM-Konfiguration.
2. Erstellen Sie ein neues datiertes Backup unter `<BACKUP_ROOT>/<CHANGE_ID>`; überschreiben Sie kein älteres Backup.
3. Erzeugen Sie eine SHA-256-Prüfsummenliste und prüfen Sie jede Datei unmittelbar.
4. Prüfen Sie Eigentümer, Modi, Verschlüsselung und Zugriff; Secretwerte niemals in Logs ausgeben.
5. Testen Sie den Restore in einer isolierten Zielumgebung oder führen Sie vor Freigabe mindestens die dokumentierte Restoreprobe des Runbooks durch.
6. Erfassen Sie Größe, Anzahl, Hashprüfung, Restoreergebnis, Aufbewahrung und Owner.

**Erwartetes Ergebnis:** Vollständiges, aktuelles, prüfsummengültiges und wiederherstellbares Pre-Change-Backup.

**Stoppbedingungen:** Aktive Schreiblast nicht kontrolliert; Datei/Volume fehlt; Prüfsumme fehlerhaft; Encryption-Material nicht wiederherstellbar; Backup nur auf demselben Ausfallmedium; Restoreprobe scheitert.

**Nachweis:** Backup-ID/Pfadreferenz, Zeit, Größe, Dateianzahl, 100-%-Hashprüfung, Restoreprotokoll und zwei Operatoren.

**Eskalation:** Backup-/Rollbackowner und Change-Leitung; bei Secret-/Datenverlustverdacht Incident-Leitung.

> Das Backup vom 10. Juli hat 29 von 29 Prüfsummen bestanden, ist aber nach den am 13. Juli vorhandenen Entwürfen veraltet. Es reicht nicht als aktuelles Pre-Change-Backup.

#### Arbeitsanweisung B5 – Geharteten Release-Kandidaten freigeben

**Verantwortlich:** Release Owner; primärer und sekundärer Operator; Business Approver; Rollbackowner

**Voraussetzungen:** B1 bis B4 bestanden; exaktes Quellarchiv und SHA-256 auf Zielhost; reproduzierbares Image; vollständige Tests; frisches Backup; Wartungsfenster; Stakeholder informiert; externe Writes bleiben false.

**Schritte:**

1. Bauen Sie den Kandidaten aus dem exakten geprüften Archiv; erfassen Sie Image-Digest und Nicht-Root-Laufzeit.
2. Starten Sie ihn isoliert auf Kandidatenport und festem Kandidaten-Volume; keine Produktionsdaten mutieren.
3. Führen Sie vollständige Unit-, Packaging-, Konfigurations-, API-, Browser-, Security- und Release-Acceptance-Tests gegen exakt dieses Artefakt aus.
4. Prüfen Sie genau K1 bis K5, keine Testdatensätze, lokale AI-Provenienz, aktuelle Quellenlage, K4-Gate, Postiz-Draft-only, Analytics-Herkunft und alle Abhängigkeitsstatus.
5. Qualifizieren Sie TLS, namentliche Identität, Actor-Attestation, Sicherheitsheader und Loopback-Bindings.
6. Rollen Sie Agent/Proxy und n8n als getrennte kontrollierte Schichten aus; prüfen Sie nach jeder Schicht und stoppen Sie bei Fehler.
7. Führen Sie den read-only Produktionssmoke und die maschinenlesbare Release-Abnahme aus.
8. Holen Sie den dokumentierten Go-/No-Go-Entscheid von allen benannten Rollen ein.

**Erwartetes Ergebnis:** Exakt identifiziertes Artefakt, alle Pflichtgates grün, sichere HTTPS-Nutzung und dokumentierte Freigabe; keine externen Providerwrites während der Abnahme.

**Stoppbedingungen:** Irgendein Pflichtgate rot; Test gegen anderes Image; Root-Prozess; HTTP liefert nutzbare UI/API/Anmeldung; `/session` fehlt; Header fehlen; n8n-Manifest weicht ab; ComfyUI strikte Readiness falsch; Backup/Rollback unsicher; externe Write beobachtet.

**Nachweis:** Commit/Archivhash, Image-Digest, Testberichte, Browsernachweise, Header-/TLS-Prüfung, n8n-Manifest, Backup-/Restorebeleg, Operatoren, Zeiten und signierter Go-/No-Go-Eintrag.

**Eskalation:** Change-Leitung; bei Sicherheits-/Datenabweichung Incident-Leitung. Kein Teil-Go für kritische Gates.

#### Arbeitsanweisung B6 – Rollback ausführen

**Verantwortlich:** Rollbackowner führt; Release Owner autorisiert; sekundärer Operator kontrolliert

**Voraussetzungen:** Rollbacktrigger erfüllt; freigegebenes altes Image/Config/Backup eindeutig; Kommunikationskanal offen; keine unkontrollierte Paralleländerung.

**Schritte:**

1. Stoppen Sie das Release und deklarieren Sie No-Go/Rollback mit Zeit und Grund.
2. Sperren Sie neue Operatoraktionen und halten Sie externe Writes auf false.
3. Stellen Sie die vorherige Agent-/Proxy-Version und – nur falls betroffen – den vorherigen n8n-Export samt passendem Encryption-Material wieder her.
4. Stellen Sie Daten ausschließlich aus dem identifizierten Backup wieder her; vermischen Sie keine Release-Schichten.
5. Prüfen Sie Container, Health, Datenbestand, Workflowaktivität und Zugriff read-only.
6. Dokumentieren Sie verlorene/neu entstandene Daten zwischen Backup und Rollback und informieren Sie Business Owner.
7. Öffnen Sie einen Incident/Postmortem; keinen erneuten Releaseversuch ohne neue Freigabe.

**Erwartetes Ergebnis:** Bekannter letzter Zustand ist wiederhergestellt, externe Writes bleiben aus, Datenabweichungen sind transparent.

**Stoppbedingungen:** Backuphash falsch; Image/Encryption-Material unklar; Restore würde neuere Daten still überschreiben; Zielvolume nicht eindeutig; parallel laufende Instanz; Rollback selbst verschlechtert Sicherheit.

**Nachweis:** Trigger, Autorisierung, verwendete Digests/Backup-ID, Befehls-/Zeitprotokoll, Nachprüfung, Datenabweichung und Kommunikation.

**Eskalation:** Incident-Leitung und Geschäftsverantwortung; Security/Datenschutz bei möglichem Daten- oder Zugriffsereignis.

### 19. Incident-Management

#### Arbeitsanweisung B7 – Incident aufnehmen und führen

**Verantwortlich:** Erste erkennende Person meldet; Incident Commander übernimmt; Service Owner untersucht

**Voraussetzungen:** Ein Sicherheits-, Identitäts-, Datenintegritäts-, Verfügbarkeits- oder externer Übergabefehler liegt vor oder wird vermutet.

**Schritte:**

1. Stoppen Sie riskante Aktionen; deaktivieren Sie keine Schutzgates zur Diagnose.
2. Klassifizieren Sie Auswirkung: Sicherheit/Datenschutz, Datenintegrität, Publishing, Identität/TLS, n8n/Automation, Modell/Quelle oder Beobachtbarkeit.
3. Sichern Sie flüchtige, sanitisierten Nachweise: Zeiten, IDs, Digests, Status und relevante Logs ohne Secrets.
4. Begrenzen Sie die Auswirkung: Operatorzugriff sperren, externe Writes false halten, fehlerhafte Schicht isolieren.
5. Benennen Sie Incident Commander, technische Verantwortung, Kommunikationsverantwortung und nächstes Update.
6. Entscheiden Sie Reparatur oder Rollback anhand der freigegebenen Kriterien; vermeiden Sie parallele unkoordinierte Änderungen.
7. Prüfen Sie nach Wiederherstellung alle betroffenen Gates und führen Sie eine Ursachenanalyse mit Maßnahmen, Ownern und Fristen durch.

**Erwartetes Ergebnis:** Kontrollierte Eindämmung, nachvollziehbare Zuständigkeit, verifizierte Wiederherstellung und umsetzbare Folgemaßnahmen.

**Stoppbedingungen:** Zielsystem/Identität unklar; Beweissicherung würde Daten verändern; Secret oder Personendaten könnten offengelegt werden; mehrere Teams ändern dieselbe Schicht; Sicherheit kann nicht bestätigt werden.

**Nachweis:** Incident-ID, Zeitlinie, Auswirkung, Beteiligte, sanitisiertes Beweisinventar, Entscheidungen, Wiederherstellungschecks und Maßnahmenliste.

**Eskalation:** Security/Datenschutz sofort bei möglicher Offenlegung; Geschäftsführung bei externer Veröffentlichung oder wesentlicher Betriebsunterbrechung; Anbieter bei vertraglich relevanter Störung.

#### Schweregrade

| Stufe | Beispiel | Reaktion |
| --- | --- | --- |
| SEV-1 | Unautorisierte Veröffentlichung, Secret-/Personendatenabfluss, falscher Tenant mit Write | Sofort stoppen, Incident Commander und Security/Datenschutz, externe Kommunikation prüfen |
| SEV-2 | Identität/TLS ausgefallen, Datenintegrität unklar, n8n erzeugt unerwartete Aktionen | Betrieb sperren, innerhalb des Bereitschaftsfensters bearbeiten, Rollback erwägen |
| SEV-3 | Einzelner Workflow/Adapter blockiert, sichere Degradation vorhanden | Sichtbar degradieren, Ticket und Owner, keine falsche Green-Anzeige |
| SEV-4 | Dokumentations-/Darstellungsfehler ohne Funktionsrisiko | Normal priorisieren und nachvollziehbar korrigieren |

### 20. Bekannte Grenzen und bewusst deaktivierte Funktionen

- Die Live-Installation ist am 13. Juli nicht gehärtet und nicht für Marketing-Freigaben bereit.
- Nvidia-1 und seine Abhängigkeiten waren beim abschließenden Bürocheck nicht erreichbar. Frühere erfolgreiche Prüfungen bleiben historische Nachweise, sind aber keine aktuelle Health-Aussage.
- Die Desktop-/Mobilabläufe und ihre bereinigten Screenshots sind für den isolierten Kandidaten abschließend geprüft; sie belegen weder die Produktionsstrecke noch einen erfolgreichen aktuellen Trendlauf mit Nvidia-Abhängigkeiten.
- Die lokalen amd64-/arm64-Images bestanden die beschriebenen Härtungs- und Schwachstellenprüfungen. Arm64 lief jedoch nur über QEMU; echte Nvidia-Hardware, TLS und Abhängigkeiten bleiben offen. Nach jeder weiteren Quelländerung sind Image, SBOM und betroffene Nachweise neu zu erzeugen.
- Externe Postiz-, Twenty-, Mautic- und Social-Provider-Schreibvorgänge sind deaktiviert.
- Eine Postiz-Freigabe darf nur einen Entwurf erzeugen; öffentliche Veröffentlichung bleibt manuell.
- Vollautomatische Plattform-Analytics fehlen; Messwerte benötigen Providerherkunft und menschliche Zuordnung.
- Firecrawl ist derzeit nicht verfügbar; SearxNG ist der nachgewiesene Rechercheadapter.
- Der isolierte ComfyUI-/FLUX-Kandidat ist technisch qualifiziert, aber kein kreativer Produktionspfad ist release-freigegeben; namentliche Sicht- und Lizenzbestätigung fehlen und automatische produktive Queue-Submission bleibt gesperrt.
- n8n läuft noch nicht im freigegebenen Postgres-/Redis-Queue-Modus; diese Migration ist ein eigener Release.
- Twenty und Mautic sind nicht für produktive CRM-Schreibvorgänge qualifiziert.
- Observability ist gestoppt; solange sie nicht wieder qualifiziert ist, fehlt eine wesentliche Betriebsabsicherung.
- Cloud-Fallback ist kein Standardweg. Vertrauliche oder personenbezogene Kampagnendaten bleiben lokal, sofern nicht eine eigene Governance-Freigabe vorliegt.
- Das konfigurierte Kimi-Credential muss beim Anbieter rotiert oder neu ausgegeben und die Route danach erneut qualifiziert werden; bis dahin bleibt Cloud-Fallback deaktiviert.
- Das öffentliche GitHub-Repository hat derzeit keinen Schutzregelsatz für `main`; ein Release darf erst nach erzwungenem Pull Request, Pflicht-CI, namentlichem Review und Sperre direkter beziehungsweise erzwungener Pushes erfolgen.
- Die regelbasierte Content-Arbeitsvorlage ist ausschließlich ein sicherer Fehlerzustand: Sie bleibt gesperrt und kann weder geprüft noch freigegeben oder geplant werden. Nach Wiederherstellung der lokalen KI ist eine neue Erstellung erforderlich.
- Vorhandene Kampagnen- und Zielgruppentexte können ambitionierte Marketingformulierungen enthalten; öffentliche Copy unterliegt immer den strengeren Evidence- und Governance-Regeln.

### 21. Abnahmechecklisten

#### Arbeitsanweisung B8 – Operator-Abnahme vor Wiederöffnung

**Verantwortlich:** Marketing Operations und ein namentlicher Sekundäranwender

**Voraussetzungen:** Technische Release-Abnahme B5 grün; Freigabe im Change-Ticket; aktuelle `<KONSOLEN-URL>` aus Servicekatalog.

**Schritte / Checkliste:**

- [ ] HTTPS ohne Warnung; HTTP liefert keine nutzbare Konsole, API, Anmeldemaske oder Sitzung.
- [ ] Persönliche Identität korrekt; kein Sammelname.
- [ ] Genau K1 bis K5, keine Demo-/Mock-/Smoke-Inhalte.
- [ ] Übersicht zeigt für K1/K2/K4 zusammen das wirksame Wochenziel 9; K3/K5 sind bis 1. August geplant und zählen jeweils 0, nicht als Rückstand.
- [ ] **Arbeitsfähigkeit** zeigt genau Recherche, Ideen & Texte, Medien, Freigabe und Redaktionsplanung mit fachlichem Status und nächstem Schritt.
- [ ] Content Studio zeigt zuerst vier regelbasierte redaktionelle Richtungen; erst die ausdrückliche Auswahl startet die lokale KI für den vollständigen kampagnenspezifischen Entwurf.
- [ ] Eine sichere Arbeitsvorlage nach KI-Fehler bleibt gesperrt und ist nicht prüf-, freigabe- oder planbar.
- [ ] Die Anwenderoberfläche zeigt keine Provider-/Modellnamen, Laufzeiten, Roh-Hashes oder internen Content-/Asset-IDs.
- [ ] Aktuelle Recherche blockiert ohne zwei unabhängige Domains und aktuelles Datum.
- [ ] Freigabe verlangt Namen, Markenfit, drei Prüfungen und konkrete Notiz.
- [ ] K4 verlangt Postiz-Referenz/Link, Auswahl der exakt gleichen lokalen Originaldatei, automatisch lokal berechneten Dateinachweis und Einwilligungsreferenzen; die Datei wird nicht an die Konsole hochgeladen.
- [ ] Postiz ist klar als Draft-only gekennzeichnet; unklarer Ausgang verhindert Blind-Retry.
- [ ] Ergebnisse verlangen Veröffentlichungsbeleg, Zeitraum, Abrufzeit, verantwortliche Person, Zuordnung und die exakte Exportdatei je verwendeter Kennzahlengruppe; ihr Nachweis entsteht automatisch lokal.
- [ ] Desktop und Mobilansicht sind lesbar; keine kritischen Browser-/Requestfehler.

**Erwartetes Ergebnis:** Ein Nicht-Techniker kann den sicheren Tagesablauf ohne mündliche Zusatzannahmen durchführen.

**Stoppbedingungen:** Ein Kästchen bleibt offen; UI behauptet Green trotz technischem Blocker; Handlung kann versehentlich veröffentlichen oder Prüfungen umgehen.

**Nachweis:** Abnahmedatum, beide Namen, Browser/Viewport, Version/Digest und bereinigte Screenshots der Schlüsselseiten.

**Eskalation:** Release Owner; bei Sicherheits-/Identitätsthema sofort No-Go.

#### Arbeitsanweisung B9 – Technische Go-/No-Go-Checkliste

**Verantwortlich:** Release Owner mit primärem und sekundärem Operator

**Voraussetzungen:** B1 bis B6 vorbereitet; alle Nachweise im Change-Ticket.

**Schritte / Checkliste:**

- [ ] Frisches Backup vollständig, 100 % Hashprüfung, Restoreprobe bestanden.
- [ ] Exaktes Quellarchiv und Image-Digest identifiziert; Non-Root-Laufzeit bestätigt.
- [ ] Vollständige Tests gegen genau dieses Artefakt grün.
- [ ] TLS-Vertrauenskette, namentliche Konten, `/session`, sichere Mutation und Actor-Attestation grün.
- [ ] HSTS, CSP `frame-ancestors 'none'` und `X-Frame-Options: DENY` vorhanden.
- [ ] Raw-Ports loopback-only; LAN nur über Allowlist-/Auth-Proxy.
- [ ] n8n-Manifest: acht IDs genau einmal aktiv, zwei genau einmal inaktiv.
- [ ] Eine exakte n8n-Version und ein unveränderlicher Digest sind genehmigt: entweder live 2.29.10 qualifiziert/gepinnt oder der geprüfte 2.29.9-Kandidat als eigener Versionswechsel akzeptiert.
- [ ] SearxNG echter Lauf; Qwen echter Lauf mit Provenienz; ComfyUI strikte Readiness und Qualifikationsjob grün.
- [ ] Firecrawl-Status wahr; nicht konfigurierte Adapter werden nicht als aktiv gemeldet.
- [ ] Postiz/Twenty/Mautic-Qualifikationen getrennt; externe Writes während Kernrelease false.
- [ ] Kimi-Credential beim Anbieter rotiert oder neu ausgegeben; Cloudroute danach separat qualifiziert oder weiterhin deaktiviert.
- [ ] Prometheus/Grafana und relevante Alerts geprüft oder Release bleibt No-Go.
- [ ] Rollbackowner, alte Digests, Datenpfade, Workflowexport und Encryption-Material eindeutig.
- [ ] Read-only Produktionssmoke sowie manuelle Desktop-/Mobilprüfung grün.
- [ ] Business Approver und beide Operatoren dokumentieren Go.
- [ ] GitHub-`main` erzwingt Pull Request, grüne Pflicht-CI, mindestens ein namentliches Review und verhindert direkte/Force-Pushes.

**Erwartetes Ergebnis:** Entweder vollständig belegtes Go oder klares No-Go mit Owner und nächstem Schritt.

**Stoppbedingungen:** Jede ungeklärte Abweichung, falscher Wahrheitsflag, nicht reproduzierbares Artefakt oder fehlender Rollbacknachweis.

**Nachweis:** Signierte Checkliste im Change-Ticket, Artefakt-/Backuphashes, Testergebnisse und Abnahmezeiten.

**Eskalation:** Change Advisory/Geschäftsverantwortung; kritische Gates dürfen nicht per Risikoakzeptanz eines Einzelnen übersprungen werden.

---

### 22. Änderungsverlauf

| Version | Datum | Änderung | Autor/Freigabe |
| --- | --- | --- | --- |
| 1.5 | 13.07.2026 | Abschließende Regression mit 450 bestandenen und 2 übersprungenen Tests, isolierte Desktop-/Mobilabläufe und Screenshots, null WCAG-A/AA-Verstöße, exakte lokale amd64-/arm64-Identitäten mit erneuerten SBOMs sowie das lokal geprüfte 190-Dateien-Quellarchiv dokumentiert; QEMU ausdrücklich von echter Nvidia-Hardwareabnahme getrennt; Transfer-, TLS-, Abhängigkeits-, n8n-, Backup- und `main`-Gates weiterhin rot | Marketing Operations / technische Freigabe ausstehend |
| 1.4 | 13.07.2026 | Abschließenden Nvidia-Verbindungsverlust, 447 bestandene plus 2 übersprungene Tests, neuesten K1-Vier-Domain-Lauf ohne vertrauenswürdiges Datum, n8n-2.29.10/2.29.9-Drift, pre-finale Browserbilder, Kimi-Schlüsselrotation und fehlenden GitHub-`main`-Schutz als offene Gates dokumentiert | Marketing Operations / technische Freigabe ausstehend |
| 1.3 | 13.07.2026 | Vollständige lokale Regression, statische Prüfungen, isolierten Nicht-Root-Container und Accessibility-Ergebnis dokumentiert; Produktionsbestand, isolierte Qwen-/SearxNG-Nachweise und weiterhin offene Quellen-, Browser-, Artefakt-, ARM64- und Produktionsgates klar getrennt; finale Image-/Archividentität bewusst offen gelassen | Marketing Operations / technische Freigabe ausstehend |
| 1.2 | 13.07.2026 | Postiz-Mediennachweis um serverseitigen Bytevergleich bei Registrierung und Übergabe ergänzt; isolierten FLUX-Schnell-API-Lauf als technisch qualifiziert dokumentiert, namentliche Sicht- und Lizenzfreigabe weiterhin offen; Wachstumsdienste über getrennte interne Datennetze und kanonische HTTPS-URLs gehärtet | Marketing Operations / technische Freigabe ausstehend |
| 1.1 | 13.07.2026 | Anwenderablauf an den gehärteten Kandidaten angeglichen: wirksames Wochenziel 9; K3/K5 bis 1. August ohne Rückstand; vier Richtungen vor expliziter lokaler KI-Erstellung; Fallback strikt gesperrt; fünf fachliche Arbeitsfähigkeiten; lokale Datei-/Exportbeweise ohne Upload oder manuelle Hash-/ID-Eingabe; technische Rohdetails aus der Anwendersicht entfernt; ComfyUI-Hash- und Encodervertrag präzisiert | Marketing Operations / technische Freigabe ausstehend |
| 1.0 | 13.07.2026 | Erstes gemeinsames Anwender- und Betriebshandbuch; genau fünf Kampagnen; klare Freigabe-, K4-, Postiz-, Analytics-, n8n-, Backup-, Release- und Incident-Regeln; aktueller Livezustand als nicht produktionsbereit dokumentiert | Marketing Operations / technische Freigabe ausstehend |

### 23. Merksätze

Für Marketing:

> **Quelle öffnen. Richtung bewusst wählen. Lokalen KI-Entwurf als Mensch prüfen. Nur einen Entwurf übergeben. Ergebnisse belegen.**

**Für Administration: Ohne Identität, TLS, Backup, exaktes Manifest, Tests und Rollback gibt es kein Go.**
