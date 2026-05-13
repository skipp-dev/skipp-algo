# SMC Lite + Pro Product Cut

## Closure Update 2026-04-06 23:18:29 CEST

Die in diesem Dokument festgehaltenen Repo-Gaps wurden inzwischen auf den
relevanten Haupt- und Nebenflaechen geschlossen.

- `scripts/smc_bus_manifest.py` ist jetzt die explizite kanonische Quelle fuer
  Surface-Rollen, Contract-Tiers, Consumer-Rollen und Preflight-Scopes des
  gesamten SMC-Konstrukts. Das Dashboard ist dort explizit als
  `pro_primary`-Surface klassifiziert.
- `artifacts/tradingview/smc_product_cut_manifest.json` spiegelt diesen Stand
  maschinenlesbar fuer Release-, Doku- und Test-Layer.
- Die Hauptpfad-Skripte tragen jetzt in-code Rollenanker: Lite-Primary im
  Core, Pro-Primary im Dashboard und Pro-Primary-Execution-Wrapper in der
  Long Strategy.
- `SMC_Long_Strategy.pine` trennt jetzt sichtbare Wrapper-Steuerung von den
  operator-only BUS-Bindings und zeigt den Plan als `Execution Trigger`,
  `Execution Invalidation` und `Execution Take Profit`.
- Die Companion-, Context-, Bridge- und Legacy-Flaechen sind repo-weit
  in-code als `companion_operator_only`, `internal` oder `legacy`
  markiert.
- `scripts/tv_preflight.ts`, die Preflight-Configs unter
  `automation/tradingview/` und
  `artifacts/tradingview/library_release_manifest.json` lesen bzw. spiegeln
  jetzt den kanonischen Produkt-Cut statt eines veralteten Datei-Sets.
- Ticket 10 ist jetzt auch im Live-Betrieb geschlossen: der Mainline-Run
  `automation/tradingview/reports/preflight-2026-04-07T19-12-02-524Z.json`
  hat den Dashboard-Settings-Pfad wieder korrekt und vollstaendig gruen
  bestaetigt.
- Der kanonische Live-Check `npm run tv:preflight:smc-mainline` ist jetzt fuer
  `SMC_Core_Engine.pine`, `SMC_Dashboard.pine` und `SMC_Long_Strategy.pine`
  vollstaendig gruen, inklusive Auth, UI, Compile, Binding und Runtime.
- Die Payload-/Schema-Layer transportieren `product_cut` jetzt bis in
  Snapshot-Bundle, Dashboard-Payload und Pine-Payload.
- Verifiziert wurde das Ganze mit fokussierten Python- und TypeScript-Tests
  sowie einem `tsc --noEmit`-Lauf.

## Post-Cut Cleanup Update 2026-04-07

Die Folgepunkte am Dokumentende sind jetzt als Doku- und Betriebsregeln
nachgezogen. Sie sind kein neuer Closure-Blocker fuer den aktiven
SMC-Hauptpfad.

## Directional Truth — 2026-04-14

Die SMC-Mainline (Core + Dashboard + Strategy) ist ein **Long-Dip-Spezialist**.
Short-Parity ist weder implizit noch still versprochen.

- `SMC_Core_Engine.pine` traegt seit v5.5 den expliziten Produktanker:
  _this script is the active long-dip specialist surface. Short-parity
  remains a separate follow-up track._
- `SMC_Dashboard.pine` und `SMC_Long_Strategy.pine` enthalten seit WP10
  analoge Klarstellungen in ihren Kopfkommentaren.
- Eine kuenftige Short-Parity-Spur wuerde als eigenstaendiger Track mit
  dediziertem Producer, separater Companion-Bindung und expliziter
  Measurement-Lane angelegt — nicht als stille Erweiterung der bestehenden
  Mainline.
- Solange kein Short-Parity-Track existiert, gelten alle Mainline-
  Empfehlungen, Validierungen und Quality-Gates als long-only scoped.

- Der Lite-Contract bleibt als eingefrorene kanonische Teilmenge im
  Product-Cut-Manifest verankert und ist der Referenzpunkt fuer Release-,
  Preflight- und Wrapper-Doku.
- `SMC_Core_Engine.pine` bleibt die einzige Lite-Primary-Surface. Eine neue
  Lite-Consumer-Surface wird bewusst nicht vorgezogen, solange sie nicht ohne
  Logikfork, neuen Producer oder neue Binding-Strecke auskommt.
- Die Pro-only-Transportbereinigung bleibt ein separater spaeterer
  Architekturpfad. Sie ist kein stiller Teil des aktiven Mainline-Contracts.
- Die begleitende Doku wurde auf diesen Stand gezogen: der Strategy-Guide,
  die manuellen Validation-Runbooks, der Doku-Index und die README-Verweise
  spiegeln jetzt denselben Mainline- und Guardrail-Stand.

## Archivierter Vorzustand 2026-04-06 22:20:48 CEST

Die folgende Bestandsaufnahme ist der unmittelbar vor dem Closure Update
dokumentierte Gap-Stand. Sie bleibt nur zur Nachvollziehbarkeit im Dokument und
beschreibt nicht mehr den aktuellen Repo-Status.

Diese Sektion dokumentiert den damaligen belastbaren Ist-Stand und trennt
zwischen dem aktiven Drei-Surface-Hauptpfad und dem breiteren SMC-Konstrukt.

### Status damals

- Der aktive release-verbindliche Hauptpfad ist weiterhin:
  `SMC_Core_Engine.pine`, `SMC_Dashboard.pine`, `SMC_Long_Strategy.pine`.
- Das breitere SMC-Konstrukt ist groesser als dieser Dreier-Scope. Dazu gehoeren
  zusaetzlich die privaten SMC-Libraries unter `SMC++/`, die generierte
  Micro-Library unter `pine/generated/`, die Context- und Overlay-Skripte
  (`SMC_*_Context`, `SMC_*_Overlay`, `SMC_HTF_Confluence`,
  `SMC_Liquidity_Structure`), die Publish-/Preflight-Pfade unter `scripts/`
  und `automation/tradingview/`, die SMC-Specs unter `spec/` sowie die breite
  SMC-Test- und Doku-Huelle.
- Der Lite/Pro Product Cut ist fuer das gesamte SMC-Konstrukt aktuell nicht
  vollstaendig umgesetzt. Umgesetzt wurde heute nur ein Teil des sichtbaren
  UI-/Doku-Schnitts am aktiven Hauptpfad.

### Was heute in den letzten 12 Stunden tatsaechlich gemacht wurde

1. Commit `590f2294` vom `2026-04-06 12:49 +0200`
   (`Implement decision-first TradingView first release UX`):
   - `SMC_Core_Engine.pine` wurde geaendert.
   - `SMC_Dashboard.pine` wurde geaendert.
   - zusaetzlich wurden PRD, Screen Spec, Ticketset,
     Implementierungsvorbereitung und der erste UI-Test angelegt bzw.
     erweitert.
   - Im Core wurde die sichtbare Lite-Surface konkret vorgezogen:
     `long_user_preset`, `compact_mode` als `Visual Mode (Lite Hero)`,
     `show_dashboard` als Decision-Detail-Schalter sowie eine Hero-Card mit
     `Action`, `Bias`, `Quality`, `Why now`, `Main risk`.
   - Im Dashboard wurde die sichtbare Surface-Trennung konkret eingefuehrt:
     `surface_mode = "Compact Detail" | "Pro Diagnostics"`, ein kompakter
     Default-Renderpfad und eine explizite Pro-Diagnostics-/Operator-Companion-
     Lesart.

2. Commit `b75b2156` vom `2026-04-06 15:38 +0200`
   (`Harden R1.1 docs and align stale regression tests`):
   - `SMC_Dashboard.pine` wurde erneut gehaertet.
   - zusaetzlich wurden `README.md`, `CHANGELOG.md`, der
     R1.1-Migrationsguide und der UI-Regressionstest weiter angepasst.
   - Inhaltlich ging es hier vor allem um Companion-/Operator-Workflow,
     Default-Surface-Haertung und Testabgleich, nicht um einen neuen Cut im
     Core oder in der Strategy.

3. Commit `ae96a30d` vom `2026-04-06 17:09 +0200`
   (`Complete first-release decision-first surfaces`):
   - in dem hier relevanten SMC-Scope wurden nur noch Docs, README,
     CHANGELOG und der UI-Test weitergezogen.
   - `SMC_Core_Engine.pine`, `SMC_Dashboard.pine` und
     `SMC_Long_Strategy.pine` wurden in diesem Commit nicht mehr geaendert.

4. Lokaler Arbeitsstand jetzt:
   - Es gibt aktuell keine uncommitted Aenderung an
     `SMC_Core_Engine.pine`, `SMC_Dashboard.pine` oder
     `SMC_Long_Strategy.pine`.
   - Die aktuellen lokalen Aenderungen sitzen in README, CHANGELOG,
     Decision-First-Dokumenten und `tests/test_tradingview_decision_first_ui.py`
     und korrigieren dort den Scope von einer falschen SMC/SkippALGO-Mischung
     zur sauberen SMC-Dreier-Surface.

### Was heute nicht gemacht wurde

- `SMC_Long_Strategy.pine` wurde in den letzten 12 Stunden nicht geaendert.
- Der Lite/Pro Product Cut wurde nicht vollstaendig auf das gesamte breitere
  SMC-Konstrukt ausgerollt.
- Es wurde heute keine vollstaendige Repo-weite Anpassung aller Context-,
  Overlay-, Library-, Spec- und Publish-Flaechen auf den Lite/Pro-Cut
  abgeschlossen.

### Ehrlicher Umsetzungsstand gegen dieses Dokument

- `SMC_Core_Engine.pine`:
  der sichtbare Lite-Hero-Cut wurde heute tatsaechlich umgesetzt.
- `SMC_Dashboard.pine`:
  der Compact-Detail-vs-Pro-Diagnostics-Schnitt wurde heute tatsaechlich
  umgesetzt und spaeter gehaertet.
- `SMC_Long_Strategy.pine`:
  die Datei ist als duenner Wrapper vorhanden, aber der heute verfolgte
  Product-Cut wurde dort nicht weiter umgesetzt.
- Gesamtziel `vollstaendig fuer das SMC-Konstrukt umgesetzt`:
  Stand jetzt nicht erreicht.

### Echte Gap-Liste gegen dieses Dokument

1. Kein repo-weiter Rollout des Lite/Pro-Cuts auf das breitere SMC-Konstrukt.
  Die heutige Umsetzung blieb auf den sichtbaren Hauptpfad beschraenkt. Die
  Context-, Overlay-, Library-, Spec- und Publish-Flaechen wurden nicht
  vollstaendig auf dieselbe Produktgrenze umgezogen.

2. `SMC_Long_Strategy.pine` wurde fuer den heutigen Product-Cut nicht zu Ende
  gezogen.
  Die Strategy existiert weiter als duenner Wrapper, aber der heute geplante
  sichtbare Product-Cut wurde dort nicht aktiv weiter umgesetzt.

3. Die Companion- und Overlay-Schicht wurde nicht in Lite / Pro /
  operator-only einsortiert.
  Skripte wie `SMC_Event_Overlay.pine`, `SMC_Liquidity_Context.pine`,
  `SMC_HTF_Confluence.pine`, `SMC_Structure_Context.pine`,
  `SMC_Orderflow_Overlay.pine`, `SMC_Profile_Context.pine`,
  `SMC_Session_Context.pine`, `SMC_Imbalance_Context.pine` und
  `SMC_Liquidity_Structure.pine` laufen weiter als separate technische
  Companion-Skripte mit eigenen Inputs oder direkten Micro-Library-Imports.
  Fuer diese Flaechen wurde heute keine saubere Produktentscheidung getroffen,
  was Lite-tauglich, Pro-only oder rein intern bleiben soll.

4. Die Release- und Preflight-Lane wurde nicht sauber auf den SMC-Dreier-Scope
  bereinigt.
  `automation/tradingview/preflight-core-dashboard.json` deckt nur Core und
  Dashboard ab. `automation/tradingview/preflight-decision-first.json` zeigt
  weiterhin `SkippALGO.pine` statt `SMC_Long_Strategy.pine`. Eine repo-weite
  Validation des breiteren SMC-Konstrukts existiert damit weiterhin nicht.

5. Der Lite-Contract wurde nicht im Manifest als kanonische Produktgrenze
  stabilisiert.
  Code-seitig existiert der Contract bereits in `scripts/smc_bus_manifest.py`
  und wird durch Contract-Tests abgesichert. Nicht abgeschlossen ist aber die
  Spiegelung in die Release- und Publish-Artefakte: das aktuelle
  `artifacts/tradingview/library_release_manifest.json` verfolgt nur die
  publizierte `smc_micro_profiles_generated`-Library und listet die drei
  Consumer, aber es kodiert nicht den 14-Kanal-Lite-Contract, nicht den
  Pro-only-Split und nicht die Produktgrenze zwischen Lite-, Pro- und
  operator-only Surface als release-relevantes Artefakt.

6. Die Specs und JSON-Schemas wurden nicht auf den Product-Cut angehoben.
  `spec/smc_dashboard_payload.schema.json`, `spec/smc_pine_payload.schema.json`
  und `spec/smc_snapshot.schema.json` kennen weiterhin keine Lite-/Pro-
  Surfacegrenze, keinen kanonischen Lite-Contract, keinen Pro-only-Bereich und
  keine explizite operator-only Consumer-Rolle fuer Dashboard oder Strategy.

7. Die private Library- und Generator-Schicht wurde nicht auf die
  Produktgrenze gespiegelt.
  `SMC++/smc_bus_private.pine` codiert weiterhin nur technische BUS-Rows,
  Packs und Support-Codes. `pine/generated/smc_micro_profiles_generated.json`
  beschreibt Generator- und Publish-Metadaten, aber keine Lite-/Pro-
  Produktschichten. Die Libraries wurden heute nicht so erweitert, dass die
  Produktgrenze im Unterbau explizit nachvollziehbar wird.

8. Die breite Doku- und Test-Huelle wurde nicht vollstaendig mitgezogen.
  Lokal korrigiert wurden nur README, CHANGELOG, die Decision-First-Dokumente
  und `tests/test_tradingview_decision_first_ui.py`. Eine vollstaendige
  Anpassung der restlichen SMC-Dokumente, Runbooks, Audit-Texte,
  Publish-Dokumente und der breiten SMC-Testhuelle auf den Lite/Pro-Cut des
  gesamten Konstrukts wurde heute nicht abgeschlossen.

9. Der Product-Cut ist nicht als repo-weite Betriebsregel verankert.
  Im Hauptpfad ist die BUS-/Surface-Trennung bereits maschinenlesbar in
  `scripts/smc_bus_manifest.py` beschrieben. Nicht repo-weit verankert ist sie
  aber fuer Overlay-, Context-, Legacy-, Release-, Spec- und Doku-Flaechen.
  Welche Surface der normale Lite-Weg ist, welche Surface Pro-only ist und
  welche Skripte nur Companion- oder Operator-Rollen haben, ist deshalb noch
  nicht als belastbarer Repo-Gesamtzustand durchgezogen.

### Datei-zu-Datei-Restliste

#### 1. Sichtbarer Hauptpfad

- `SMC_Long_Strategy.pine`
  Hier sitzt der groesste offene Hauptpfad-Gap. Die Datei ist funktional ein
  stabiler 8-Kanal-Wrapper, aber der Product-Cut ist dort noch nicht fertig.
  Es fehlt eine saubere Trennung zwischen sichtbarer Wrapper-Steuerung und
  operator-only Binding-Flaeche, eine explizite Produktlesart im Code und eine
  klare Einordnung der Datei als Pro-/Execution-Surface im breiteren
  SMC-Konstrukt.

- `SMC_Core_Engine.pine`
  Kein primaerer lokaler UI-Blocker mehr fuer den heutigen sichtbaren Cut.
  Offene Arbeit ist hier nicht der Hero selbst, sondern die repo-weite
  Propagierung seines 14-Kanal-Lite-Contracts in Automation, Specs,
  Artefakte und Companion-Flaechen.

- `SMC_Dashboard.pine`
  Kein primaerer lokaler UI-Blocker mehr fuer den Compact-vs-Pro-Split.
  Offen ist hier vor allem die Anbindung an den breiteren Repo-Zustand:
  Companion-Rolle, Release-Scope, Specs, Overlay-Handoff und restliche
  Doku-/Test-Schicht.

#### 2. Companion-, Context- und Overlay-Skripte

- `SMC_Event_Overlay.pine`
  Nutzt weiterhin direkte `smc_micro_profiles_generated`-Imports und eine
  eigene Surface-Logik. Es ist nicht entschieden und nicht dokumentiert, ob
  diese Flaeche Pro-only Companion, operator-only oder interne Spezialflaeche
  ist.

- `SMC_Orderflow_Overlay.pine`
  Gleiches Problem: technisch aktiv, aber ohne Produktklassifikation gegen den
  Lite/Pro-Cut.

- `SMC_Liquidity_Context.pine`
  Keine Einordnung in Lite / Pro / intern. Bleibt eine technische
  Direkt-Consumer-Flaeche.

- `SMC_HTF_Confluence.pine`
  Keine Produktrolle im Cut verankert; weiterhin nur technische Companion-
  Flaeche.

- `SMC_Imbalance_Context.pine`
  Keine Produktrolle im Cut verankert; weiterhin nur technische Companion-
  Flaeche.

- `SMC_Structure_Context.pine`
  Keine Produktrolle im Cut verankert; weiterhin nur technische Companion-
  Flaeche.

- `SMC_Session_Context.pine`
  Keine Produktrolle im Cut verankert; weiterhin nur technische Companion-
  Flaeche.

- `SMC_Profile_Context.pine`
  Keine Produktrolle im Cut verankert; weiterhin nur technische Companion-
  Flaeche.

- `SMC_Liquidity_Structure.pine`
  Keine Produktrolle im Cut verankert; weiterhin nur technische Companion-
  Flaeche.

#### 3. Legacy-, Bridge- und Rand-Surfaces

- `SMC_TV_Bridge.pine`
  Nicht in den Product-Cut einsortiert. Unklar, ob out-of-scope Bridge,
  operator-only Hilfsflaeche oder zu entfernende Randflaeche.

- `SMC++.pine`
  Historische oder parallele SMC-Flaeche ohne saubere Einordnung gegen den
  aktiven Dreier-Scope.

- `SMC_Core_Zones.pine`
  Weiter im Repo vorhanden, aber nicht sauber als legacy / internal /
  deprecated gegen den Product-Cut markiert.

- `SMC Core + Zones.pine`
  Gleiche Luecke wie bei `SMC_Core_Zones.pine`: vorhanden, aber nicht sauber
  gegen den aktiven Product-Cut abgegrenzt.

#### 4. Contract-, Manifest- und Automation-Schicht

- `scripts/smc_bus_manifest.py`
  Diese Datei ist bereits der code-seitige Single Source of Truth fuer BUS-,
  Lite-, Pro-only- und Strategy-Contract. Offen ist nicht ihre Existenz,
  sondern ihre Erweiterung um repo-weite Surface-Rollen und ihre Nutzung durch
  Automation, Release-Artefakte, Specs und Docs.

- `artifacts/tradingview/library_release_manifest.json`
  Spiegelt derzeit nur den Micro-Library-Publish. Der Product-Cut des
  SMC-Konstrukts wird dort nicht als release-verbindliches Artefakt abgebildet.

- `automation/tradingview/preflight-core-dashboard.json`
  Deckt nur Core und Dashboard ab. Long Strategy fehlt.

- `automation/tradingview/preflight-decision-first.json`
  Ist fuer den SMC-Scope weiterhin falsch, weil dort `SkippALGO.pine` statt
  `SMC_Long_Strategy.pine` verdrahtet ist.

- `scripts/tv_preflight.ts`
  Nutzt die bestehenden Config-Dateien, aber die Produktgrenze des
  Lite/Pro-Cuts wird nicht aus einer kanonischen Surface-Rollenquelle gezogen.

- `package.json`
  Die npm-Einstiege spiegeln den falschen oder unvollstaendigen Preflight-Scope
  weiter, solange die Config-Dateien nicht bereinigt und erweitert sind.

- `SMC++/smc_bus_private.pine`
  Technisch korrekt fuer BUS-Codes, aber nicht um Produktrollen oder eine
  explizite Lite-/Pro-Semantik erweitert.

- `pine/generated/smc_micro_profiles_generated.json`
  Enthält Generator- und Publish-Metadaten, aber keine Spiegelung der
  Produktgrenze des Lite/Pro-Cuts.

#### 5. Spec- und Schema-Schicht

- `spec/smc_dashboard_payload.schema.json`
  Kennt keine Surface-Rolle, keinen Lite-/Pro-Split und keinen kanonischen
  Produktcontract fuer Dashboard als Companion.

- `spec/smc_pine_payload.schema.json`
  Kennt keine Lite-/Pro-Produktgrenze und keine Consumer-Rolle der aktiven
  TradingView-Surfaces.

- `spec/smc_snapshot.schema.json`
  Kennt weiterhin nur Daten- und Layering-Strukturen, aber keine
  Produktoberflaechen- oder Surface-Rollen.

- `spec/smc_delivery_bundle.schema.json`
  Muss nachgezogen werden, wenn der Product-Cut als lieferbares Repo-Artefakt
  end-to-end verankert werden soll.

#### 6. Doku-Schicht

- `docs/TRADINGVIEW_STRATEGY_GUIDE.md`
  Ist aktuell ein SkippALGO-Strategieguide und nicht der benoetigte Guide fuer
  `SMC_Long_Strategy.pine` als BUS-Wrapper.

- `docs/smc-validation-status.md`
  Dokumentiert weiter die Validierungs-/Automation-Lage, aber nicht den
  vollstaendigen Product-Cut des breiteren SMC-Konstrukts.

- `docs/smc-microstructure-ui-operator-runbook.md`
  Nicht auf den Lite/Pro-Cut des breiteren SMC-Konstrukts angehoben.

- `docs/smc-microstructure-ui-architecture.md`
  Nicht auf die Produktgrenze zwischen Lite, Pro und Companion-Flaechen
  angehoben.

- `docs/smc-microstructure-ui-audit.md`
  Nicht auf den finalen Product-Cut des breiteren Konstrukts angehoben.

- `docs/smc-bus-roadmap.md`
  Bus-Roadmap ist nicht auf die neue Produktgrenze gespiegelt.

- `docs/smc-bus-target-matrix.md`
  Target-Matrix ist nicht auf Surface-Rollen und Product-Cut gespiegelt.

- `docs/smc-bus-v2-audit.md`
  Audit-Dokument ist nicht auf Lite-/Pro-/operator-only Produktrollen
  gespiegelt.

- `docs/SMC_Dashboard_Long_Dip_Guide_DE.md`
  Muss gegen den heutigen Product-Cut und die Strategy-Rolle neu gelesen und
  gegebenenfalls nachgezogen werden.

- `docs/SMC_Dashboard_Long_Dip_Guide_EN.md`
  Gleiche Luecke wie in der DE-Version.

#### 7. Test- und Review-Gate-Schicht

- `tests/test_tradingview_decision_first_ui.py`
  Deckt aktuell nur einen schmalen Ausschnitt des Product-Cuts ab. Die
  breiteren Companion-, Release-, Spec- und Role-Gaps sind dort nicht gepinnt.

- `tests/test_smc_bus_manifest_contract.py`
  Sichert bereits den BUS-Contract ab. Offen ist die Erweiterung um
  Surface-Rollen, Release-Artefakte und Repo-weite Product-Cut-Regeln.

- `tests/test_smc_integration_release_gate_scripts.py`
  Sichert Release-Gates, aber nicht den SMC-Dreier-Scope und nicht den
  korrigierten Preflight-Scope des Product-Cuts.

- `tests/test_smc_split_consumers.py`
  Sichert Producer-vs-Consumer fuer den Hauptpfad, aber nicht die Einordnung
  der Companion-, Overlay- und Legacy-Flaechen in den Product-Cut.

- Die breite `tests/test_smc*.py`-Huelle
  Ist gross, aber nicht systematisch auf Lite-/Pro-/operator-only Rollen des
  gesamten Konstrukts ausgerichtet. Der fehlende Teil ist kein pauschales
  Umschreiben aller Tests, sondern das Hinzufuegen weniger harter
  review-blocking Gate-Tests fuer die Produktgrenze.

### Action Plan Zum 100%-Schliessen Der Gaps

#### Phase 1. Kanonische Produktgrenze als Single Source of Truth festziehen

1. `scripts/smc_bus_manifest.py` um repo-weite Surface-Rollen erweitern:
   `lite_primary`, `pro_primary`, `companion_operator_only`, `internal`,
   `legacy`.
2. Alle aktiven, Companion-, Overlay-, Context-, Bridge- und Legacy-Dateien in
   dieser Datei explizit klassifizieren.
3. Einen maschinenlesbaren Product-Cut-Artefaktpfad definieren, entweder als
   Erweiterung des bestehenden Release-Manifests oder als neues dediziertes
   `smc_product_cut_manifest`-Artefakt.

Definition of Done:

- Es gibt genau eine kanonische Python-Quelle fuer Surface-Rollen und
  Lite-/Pro-Contracts.
- Keine SMC-Pine-Datei bleibt unklassifiziert.

#### Phase 2. Sichtbaren Hauptpfad fertigziehen

1. `SMC_Long_Strategy.pine` produktisieren:
   Setup-Steuerung klar gruppieren, Binding-Flaeche explizit als operator-only
   markieren, Wrapper-Rolle im Code selbst sichtbar machen.
2. `SMC_Core_Engine.pine` und `SMC_Dashboard.pine` nur dort nachziehen, wo die
   neue kanonische Rollenquelle oder Produktterminologie noch nicht sichtbar
   genug gespiegelt ist.
3. Den Hauptpfad so angleichen, dass Core, Dashboard und Strategy dieselbe
   Produktsprache und dieselbe Rollenlogik tragen.

Definition of Done:

- `SMC_Long_Strategy.pine` ist kein halb-offener Wrapper mehr, sondern eine
  klar produktisierte Execution-Surface.
- Die drei Hauptpfad-Dateien lesen sich als zusammengehoeriges Produkt.

#### Phase 3. Companion-, Overlay- und Legacy-Flaechen sauber einsortieren

1. Fuer jedes Context-/Overlay-Skript eine explizite Produktentscheidung
   treffen: Pro-only Companion, operator-only Spezialflaeche oder internal.
2. Diese Rolle im Dateikopf, in zugehoerigen Guides und in der kanonischen
   Rollenquelle spiegeln.
3. Legacy- und Bridge-Dateien explizit als `legacy` oder `internal` markieren,
   damit sie in Reviews nicht weiter als ungeklaerte Produktflaechen auftauchen.

Definition of Done:

- Kein aktives SMC-Skript ist mehr rollenlos.
- Legacy- und Randflaechen sind explizit abgegrenzt.

#### Phase 4. Release-, Preflight- und Publish-Lane auf den Product-Cut spiegeln

1. `automation/tradingview/preflight-core-dashboard.json` auf den gewuenschten
   Hauptpfad anheben oder durch eine vollstaendige SMC-Hauptpfad-Config
   ersetzen.
2. `automation/tradingview/preflight-decision-first.json` von SkippALGO auf
   `SMC_Long_Strategy.pine` umstellen oder in eine neue SMC-only Config
   ueberfuehren.
3. `scripts/tv_preflight.ts` und `package.json` so anpassen, dass die aktive
   Preflight-Lane die kanonische Rollen-/Surface-Quelle nutzt.
4. Das Release-Manifest so erweitern, dass neben der Micro-Library auch der
   Produktcut des SMC-Konstrukts maschinenlesbar gespiegelt wird.

Definition of Done:

- Preflight-Configs und npm-Einstiege zeigen keinen falschen Scope mehr.
- Release-Artefakte spiegeln die echte Produktgrenze.

#### Phase 5. Specs und Schemas auf Produktrollen heben

1. `spec/smc_dashboard_payload.schema.json`,
   `spec/smc_pine_payload.schema.json`, `spec/smc_snapshot.schema.json` und bei
   Bedarf `spec/smc_delivery_bundle.schema.json` um Produktmetadaten erweitern.
2. Surface-Rolle, Contract-Tier und relevante Consumer-Rolle explizit in den
   Schemas abbilden.
3. Beispielartefakte und zugehoerige Tests auf die neuen Felder anheben.

Definition of Done:

- Die Produktgrenze ist nicht nur in Pine und Tests, sondern auch in den
  lieferbaren Schemas verankert.

#### Phase 6. Doku-Layer konsequent nachziehen

1. `docs/TRADINGVIEW_STRATEGY_GUIDE.md` auf eine echte
   `SMC_Long_Strategy.pine`-Wrapper-Doku umschreiben oder ersetzen.
2. `docs/smc-validation-status.md` auf den heutigen Product-Cut und die neue
   Rollenarchitektur anheben.
3. Runbooks, Audits und Roadmaps fuer Microstructure, BUS und Validation gegen
   dieselbe Surface-Rollenquelle spiegeln.
4. Stale SkippALGO- oder scope-fremde TradingView-Referenzen aus der SMC-Doku
   entfernen.

Definition of Done:

- Alle relevanten SMC-Dokumente sprechen denselben Scope.
- Kein Review kann mehr auf scope-fremde oder rollenlose SMC-Doku zeigen.

#### Phase 7. Review-blocking Tests als neue harte Gates einfuehren

1. `tests/test_tradingview_decision_first_ui.py` auf den breiteren Product-Cut
   erweitern.
2. `tests/test_smc_bus_manifest_contract.py` um Surface-Rollen und
   Product-Cut-Artefakte erweitern.
3. Neue Gates hinzufuegen fuer:
   - Preflight-Scope-Paritaet
   - Release-Artefakt-Paritaet
   - Spec-Surface-Metadaten
   - Companion-/Legacy-Rollenklassifikation
   - SMC-Guide-Alignment

Definition of Done:

- Ein Review kann fehlende Rollen, falsche Preflight-Ziele oder stale Doku
  nicht mehr nur textlich entdecken; die Tests schlagen davor schon fehl.

#### Phase 8. Abschlussvalidierung und Review-Paket

1. Fokus-Tests fuer Manifest, Hauptpfad, Preflight-Scope, Specs und Docs
   gruenerstellen.
2. Repo-weites Diff gegen den Product-Cut manuell gegenlesen.
3. Eine kurze Abschlussmatrix erzeugen: Datei, Rolle, Contract-Tier,
   Validierungsstatus, Review-Status.

Definition of Done:

- Der Product-Cut ist in Code, Artefakten, Specs, Docs und Tests deckungsgleich.
- Die typische Review-Frage `welche Datei gehoert zu Lite, Pro oder operator-only und wo ist das abgesichert?` laesst sich direkt aus dem Repo selbst beantworten.

### Reihenfolge Mit Hoechstem Hebel

1. `scripts/smc_bus_manifest.py` erweitern.
2. `SMC_Long_Strategy.pine` fertigziehen.
3. Preflight-Configs und Release-Artefakte auf den neuen Single Source of Truth
   umstellen.
4. Specs nachziehen.
5. Docs nachziehen.
6. Review-blocking Tests zuletzt so scharf schalten, dass danach keine stille
   Drift mehr durchgeht.

### Review-sichere Abschlusskriterien

Der Gap ist erst dann wirklich geschlossen, wenn gleichzeitig gilt:

1. jede SMC-Pine-Datei im Repo eine explizite Surface-Rolle hat,
2. der Lite-, Pro- und Strategy-Contract in einer kanonischen Quelle liegt,
3. Preflight und Release-Artefakte denselben Scope spiegeln,
4. Specs dieselbe Produktgrenze tragen,
5. alle relevanten Guides und Runbooks denselben Scope beschreiben,
6. Tests diese Regeln fail-closed absichern.

## Ziel

Dieses Dokument zieht die Produktgrenze fuer einen benutzerfreundlicheren
TradingView-Rollout, ohne die aktive Long-Dip-Engine logisch zu forkieren.
Die Kernidee ist einfach:

- Lite ist die normale Operator-Surface.
- Pro ist die Diagnose-, Tuning- und Automations-Surface.
- Beide laufen auf derselben aktiven Engine.

## Aktuelle Repo-Wahrheit

- `SMC_Core_Engine.pine` ist der einzige aktive Producer und bereits die
  eigentliche Single-Script-Operator-Surface.
- `SMC_Dashboard.pine` ist ein reiner BUS-Consumer fuer Diagnose und Erklaerung.
- `SMC_Long_Strategy.pine` ist ein duenner BUS-Consumer fuer ausfuehrbare
  Long-Entries.
- `long_user_preset` und `compact_mode` bleiben die sichtbaren Operator-Anker.

Die Lite/Pro-Trennung darf deshalb keine zweite Logikfamilie erzeugen. Sie ist
eine Produkt- und Surface-Grenze, keine neue Signal-Engine.

## Contract-Layer

### 1. Executable Core

Das ist der kleinste stabile Contract, der echte Orders und Backtests tragen
kann. Er wird heute bereits von `SMC_Long_Strategy.pine` verbraucht.

- `BUS Armed`
- `BUS Confirmed`
- `BUS Ready`
- `BUS EntryBest`
- `BUS EntryStrict`
- `BUS QualityScore`
- `BUS Trigger`
- `BUS Invalidation`

### 2. Lite Surface

Lite ergaenzt den Executable Core nur um die Signale, die eine Hero-Surface
ohne tiefe Diagnose ermoeglichen.

- `BUS ZoneActive`
- `BUS SourceKind`
- `BUS StateCode`
- `BUS TrendPack`
- `BUS LeanPackA`
- `BUS LeanPackB`

Zusammen mit dem Executable Core ergibt das den kanonischen Lite-Contract mit
14 Kanaelen.

### 3. Pro-Only Surface

Alles andere bleibt Pro-only. Das sind die Diagnose-, Audit- und Detailkanaele,
die fuer Endnutzer nicht verpflichtend sein sollten:

- `BUS MetaPack`
- `BUS LtfDeltaState`
- `BUS SafeTrendState`
- `BUS MicroProfileCode`
- `BUS ReadyBlockerCode`
- `BUS StrictBlockerCode`
- `BUS VolExpansionState`
- `BUS DdviContextState`
- `BUS StopLevel`
- `BUS Target1`
- `BUS Target2`

Hinzu kommen auf der aktiven Pro-Surface jetzt drei klar getrennte Lagen:

- direkte Diagnostic Rows fuer Gates und Quality:
  `BUS SessionGateRow`, `BUS MarketGateRow`, `BUS VolaGateRow`,
  `BUS MicroSessionGateRow`, `BUS MicroFreshRow`, `BUS VolumeDataRow`,
  `BUS QualityEnvRow`, `BUS QualityStrictRow`, `BUS CloseStrengthRow`,
  `BUS EmaSupportRow`, `BUS AdxRow`, `BUS RelVolRow`, `BUS VwapRow`,
  `BUS ContextQualityRow`, `BUS QualityCleanRow`, `BUS QualityScoreRow`,
  `BUS SdConfluenceRow`, `BUS SdOscRow`, `BUS VolRegimeRow`,
  `BUS VolSqueezeRow`
- explizite Diagnostic-Support-Codes:
  `BUS LtfDeltaState`, `BUS SafeTrendState`, `BUS MicroProfileCode`,
  `BUS ReadyBlockerCode`, `BUS StrictBlockerCode`,
  `BUS VolExpansionState`, `BUS DdviContextState`
- direkte Detail-Channels fuer wiederhergestellte Monolith-Tiefe:
  `BUS ZoneObTop`, `BUS ZoneObBottom`, `BUS ZoneFvgTop`,
  `BUS ZoneFvgBottom`, `BUS SessionVwap`, `BUS AdxValue`,
  `BUS RelVolValue`, `BUS StretchZ`, `BUS StretchSupportMask`,
  `BUS LtfBullShare`, `BUS LtfBiasHint`, `BUS LtfVolumeDelta`,
  `BUS ObjectsCountPack`

Die frueheren Legacy-Compat-Exports (`BUS HardGatesPackA/B`,
`BUS QualityPackA/B`, `BUS EnginePack`) sind inzwischen aus dem Producer
entfernt und gehoeren nicht mehr zum aktiven Pro-Vertrag.

## Lite-Produktdefinition

Lite ist nicht "weniger Engine". Lite ist "weniger Setup-Friction".

Lite soll deshalb diese Regeln einhalten:

- Standardnutzer arbeiten primaer mit `SMC_Core_Engine.pine`.
- `long_user_preset` bleibt die primaere Bedienebene.
- `compact_mode` ist die normale Freigabe-Surface fuer geteilte oder solo
  genutzte Charts.
- Es gibt keine Pflicht, zusaetzlich Dashboard- oder Strategy-Skripte per
  `input.source()` zu verdrahten.
- Die Hero-Surface zeigt nur das, was man fuer Entscheidungen schnell lesen
  muss: Lifecycle, Direction/Bias, Signal Quality, Event Risk Light,
  Structure Light, OB/FVG Light, Session Light und Risk Levels.

Lite darf ausdruecklich nicht:

- die Score- oder Gate-Semantik von Pro veraendern,
- die UI-gekoppelten Diagnosepacks als Pflicht-Setup behandeln,
- Pro-Debug-Tiefe als normales Nutzerziel verkaufen.

## Pro-Produktdefinition

Pro ist die volle Split-Surface fuer Nutzer, die das System tunen, auditieren,
debuggen oder strategisch ausfuehren wollen.

Pro umfasst:

- `SMC_Core_Engine.pine`
- `SMC_Dashboard.pine`
- `SMC_Long_Strategy.pine`
- den vollen 64-Kanal-BUS-Contract

Das aktive Dashboard nutzt derzeit den kompletten 64-Kanal-Producer-Vertrag.

Pro darf bewusst mehr Friction haben, wenn diese Friction echte Diagnose- oder
Automationsfaehigkeit liefert.

## Praktische Produktregel

Wenn ein Feld nur dazu dient, Dashboard-Zeilen oder Debug-Erklaerungen
aufzubauen, gehoert es nicht in Lite.

Wenn ein Feld eine Entscheidung auf der Operator-Surface sichtbar oder
ausfuehrbar macht, darf es in Lite bleiben.

## C9-Schnitt fuer Pro-only Packs

Nach dem Lite/Pro-Cut ist der naechste sinnvolle Cleanup-Schritt kein weiterer
Umbau des Lite-Contracts, sondern ein gezielter Pro-only-Schnitt.

### C9.1 Rebuild-Kandidaten

Die gepackte Rebuild-Lane ist jetzt abgeschlossen. Die frueheren Resttransporte
`BUS ModulePackD` und `BUS ReadyStrictPack` wurden durch explizite
Support-Codes ersetzt:

- `BUS LtfDeltaState`
- `BUS SafeTrendState`
- `BUS MicroProfileCode`
- `BUS ReadyBlockerCode`
- `BUS StrictBlockerCode`
- `BUS VolExpansionState`
- `BUS DdviContextState`

`BUS ModulePackA` wurde bereits in direkte Rows fuer `BUS SdConfluenceRow`,
`BUS SdOscRow`, `BUS VolRegimeRow` und `BUS VolSqueezeRow` ueberfuehrt.
Der fruehere `ModulePackB`-Transport ist inzwischen retired. Vor dem Cut wurden
die sichtbaren `Session VWAP`-, `EMA Fast`- und `EMA Slow`-Overlays aus dem
`plot()`-Budget in line-basierte Overlays verschoben. Danach wurde
`BUS ModulePackB` durch `BUS VolExpandRow`, `BUS DdviRow`,
`BUS StretchSupportMask` und `BUS LtfBiasHint` ersetzt.

Die Engine liegt jetzt bei `64 / 64` Plots mit einem aktiven
`64`-Kanal-Pro-Vertrag. `Swing` und `Objects` wurden zunaechst ueber
`BUS SwingRow` und `BUS ObjectsCountPack` aus `ModulePackC` herausgezogen;
spaetere direkte Modul-Zeilen wurden nun in `BUS ModulePackD`
konsolidiert. Die lokale Ableitung der Zeilen `Long Debug`,
`Debug Flags`, `Long Triggers` und `Risk Plan` hat zusaetzlich
`BUS DebugStateRow`, `BUS DebugFlagsRow`, `BUS LongTriggersRow` und
`BUS RiskPlanRow` retired. Danach wurde
`BUS MicroModifierMask` in die `Micro Profile`-Semantik gefaltet, bevor
`BUS ReadyGateRow` und `BUS StrictGateRow` zu `BUS ReadyStrictPack`
konsolidiert wurden. Danach wurde `BUS QualityBoundsPack` als fester
`25 / 100`-Supportkanal in lokale Dashboard-Formatierung verlagert. Danach
wurde `BUS EventRiskRow` entfernt; Dashboard und Event Overlay leiten den
Status jetzt lokal aus `LeanPackA.slot2` ab. Zuletzt wurden `BUS VolExpandRow`
und `BUS DdviRow` entfernt; `BUS ReadyStrictPack` transportiert diese
Semantik jetzt in Slot `2` und Slot `3`. Danach wurden `BUS LtfDeltaRow`,
`BUS SwingRow` und `BUS MicroProfileRow` durch `BUS ModulePackD` ersetzt.
Die finale Slice hat anschliessend `BUS ModulePackD` und
`BUS ReadyStrictPack` vollstaendig retired und durch die expliziten
Support-Codes `LtfDeltaState`, `SafeTrendState`, `MicroProfileCode`,
`ReadyBlockerCode`, `StrictBlockerCode`, `VolExpansionState` und
`DdviContextState` ersetzt. Es bleibt damit keine gepackte Resttransport-
Oberflaeche mehr auf der aktiven Producer-Surface.

### C9.2 Reduce-Kandidaten

Diese direkte Quality-Row-Lage ist die reduzierte Nachfolge der alten
`QualityPackA/B`-Verdichtung und traegt dieselbe fachliche Aussage mit weniger
UI-Kopplung:

- `BUS CloseStrengthRow`
- `BUS EmaSupportRow`
- `BUS AdxRow`
- `BUS RelVolRow`
- `BUS VwapRow`
- `BUS ContextQualityRow`
- `BUS QualityCleanRow`
- `BUS QualityScoreRow`

`BUS QualityPackA` und `BUS QualityPackB` sind retired; die direkten
Quality-Rows sind jetzt der einzige aktive Vertrag fuer diese Diagnoseebene.

### C9.3 Stabile Pro-Support-Channels

Diese Kanaele bleiben auch nach C9 stabile Support- oder Level-Contracts und
sollen nicht leichtfertig neu zugeschnitten werden:

- `BUS MetaPack`
- `BUS ObjectsCountPack`
- `BUS StopLevel`
- `BUS Target1`
- `BUS Target2`

### C9 Guardrails

- Der Executable Core bleibt unveraendert.
- Der Lite-Contract bleibt eingefroren.
- `SMC_Long_Strategy.pine` behaelt seinen aktuellen 8-Kanal-Contract.
- C9 darf Pro-Diagnostik entkoppeln, aber keine neue Logikfamilie erzeugen.

## Naechste Umsetzung nach diesem Cut

Diese Punkte bleiben Guardrails fuer spaetere Folgeslices, nicht offene
Release-Blocker fuer den aktuellen Product-Cut.

1. Den Lite-Contract im Manifest als kanonische Teilmenge stabil halten.
  Status 2026-04-07: aktiv eingefroren; Aenderungen daran brauchen einen
  separaten Product-Cut-Entscheid statt stiller Scope-Ausweitung.
2. Eine dedizierte Lite-Consumer-Surface nur dann bauen, wenn sie ohne neue
  Logikforks auskommt.
  Status 2026-04-07: bewusst nicht aktiv; `SMC_Core_Engine.pine` bleibt die
  normale Lite-Surface.
3. Pro-only Packs spaeter separat entkoppeln oder neu schneiden, ohne den
  Lite-Contract zu verwackeln.
  Status 2026-04-07: als spaeterer Domain-/Bus-Folgepfad dokumentiert, nicht
  als laufende Mainline-Aenderung.

## Oberflaechenkonzept nach PM/UX-Review 2026-04-07

Dieses Zielbild aendert nicht den eingefrorenen Lite-/Pro-Contract. Es zieht
die sichtbare Surface-Hierarchie fuer Core, Dashboard und Strategy so gerade,
dass das Produkt aus Chart-Nutzersicht schneller lesbar, glaubwuerdiger und
klarer differenziert wird.

### Kernentscheidung

- Es gibt genau eine taegliche Lite-Primary-Surface: `SMC_Core_Engine.pine`.
- `SMC_Dashboard.pine` ist keine zweite Lite-Flaeche, sondern die explizite
  Pro-Companion-Surface fuer Diagnose, Audit, Tuning und Review.
- `SMC_Long_Strategy.pine` ist die explizite Execution-Surface fuer Backtest,
  Staging und regelgebundene Ausfuehrung.
- Die drei Flaechen teilen dieselbe Zustandslogik, aber nicht dieselbe
  Informationstiefe.

### 1. Core als einzige Lite-Primary-Surface

Der Core bleibt der normale taegliche Einstieg. Ein Nutzer soll auf einem
einzelnen Chart ohne zusaetzliche BUS-Verdrahtung verstehen koennen, ob jetzt
Beobachten, Vorbereiten oder Handeln angebracht ist.

Der sichtbare Core muss deshalb primaer diese Fragen beantworten:

- Was ist die aktuelle Handlung: `WAIT`, `BLOCKED`, `PREPARE LONG`,
  `READY LONG`, `ENTER LONG`.
- Warum genau ist dieser Zustand aktiv.
- Wie hoch ist das Vertrauensniveau.
- Wo liegen Trigger und Invalidation, sobald der Zustand handlungsfaehig ist.

Die Hero-Surface bleibt deshalb der Hauptanker. Sie soll in dieser Reihenfolge
lesen:

- `Action`
- `Bias`
- `Quality`
- `Why now`
- `Main risk`

Fuer Lite gelten dabei diese Produktregeln:

- `Show decision detail` ist kein zweiter Primary-Mode, sondern ein bewusster
  Wechsel in erklaerende Begleitinformation.
- Interne Diagnosekuerzel wie `LTF`, `HTF`, `SD`, `DDVI` oder `Vola` gehoeren
  nicht in die primaere Hero-Sprache.
- Wenn Diagnosebegriffe auf Lite sichtbar bleiben, muessen sie zuerst als
  Trader-Sprache formuliert werden und duerfen die technische Kurzform hoechstens
  in Klammern tragen.
- Die Lite-Surface verkauft keine Modul- oder Gate-Tiefe als Produktkern,
  sondern eine klare Entscheidungsfuehrung.

### 2. Dashboard als explizite Pro-Companion-Surface

Das Dashboard bleibt wertvoll, aber seine Rolle muss enger gezogen werden. Es
ist nicht die zweite normale Nutzersurface, sondern die Companion-Flaeche fuer
Nutzer, die den Zustand erklaeren, pruefen oder systematisch optimieren wollen.

Die Produktrolle des Dashboards ist damit:

- Zustand begruenden
- Blocker sichtbar machen
- Risiko- und Kontextlogik auditierbar machen
- Modul- und Gate-Tiefe fuer Pro-Nutzer oeffnen

Fuer diese Surface gelten folgende Regeln:

- `Compact Detail` ist nur eine Pro-Zusammenfassung, nicht die eigentliche
  Lite-Surface.
- `Pro Diagnostics` bleibt operator-orientiert und darf Friction haben, aber
  nur dort, wo sie echte Diagnosefaehigkeit liefert.
- Die erste sichtbare Ebene soll Entscheidungs- und Blockerlogik ordnen,
  nicht sofort die volle interne Bus-Tiefe ausbreiten.
- Technische Codes bleiben erlaubt, aber nie ohne lesbare Klartextaussage.

Produktsprachlich gilt fuer das Dashboard deshalb:

- erst Klartext wie `Need confirmed setup`, `Session blocked` oder
  `Signal Quality blocked`
- dann optional technische Herleitung
- nie umgekehrt

### 3. Strategy als saubere Execution-Surface

Die Strategy ist nicht die Signal-Discovery-Flaeche, sondern die klare
Ausfuehrungs- und Backtest-Surface. Sie bleibt bewusst klein und wird genau
dann geoeffnet, wenn ein Nutzer aus einem vorhandenen Signalzustand ein
regelgebundenes Setup ableiten oder testen will.

Die Strategy soll deshalb sichtbar nur vier Fragen steuern:

- Welcher Entry-Zustand ist ausfuehrbar.
- Welche Mindestqualitaet ist erlaubt.
- Ob ein Take Profit verwendet wird.
- Wie gross der Take-Profit-Abstand in `R` ist.

Die sichtbaren Wrapper-Controls bleiben entsprechend klein:

- `Entry Mode`
- `Min Quality Score`
- `Take Profit R`
- `Use Take Profit`

Der Chart selbst zeigt nur den ausfuehrbaren Plan:

- `Execution Trigger`
- `Execution Invalidation`
- `Execution Take Profit`

Die Strategy bleibt damit die sauberste Pro-Execution-Surface des Stacks und
soll auch in Doku und Positionierung genau so verkauft werden.

### Surface-Regeln ueber alle drei Flaechen

Jede aktive Hauptflaeche bekommt genau einen Job:

- Core = entscheiden
- Dashboard = verstehen
- Strategy = ausfuehren

Fuer alle drei gilt dieselbe Zustandsleiter:

- `WAIT`
- `BLOCKED`
- `PREPARE LONG`
- `READY LONG`
- `ENTER LONG`

Fuer alle drei gilt dieselbe Sprachregel:

- Zustand vor Technik
- Klartext vor Kuerzel
- Risiko vor Modul-Erklaerung

Fuer alle drei gilt dieselbe Vertrauenslogik:

- `Strong` = handlungsnah
- `Usable` = brauchbar mit Restvorbehalt
- `Thin` = nur beobachten
- `Provisional` = Daten- oder Kontextvorsicht

### UX-Definition of Done fuer den Hauptpfad

Der sichtbare Hauptpfad ist erst dann wirklich produktisiert, wenn ein Nutzer
auf einem nackten Chart in weniger als zehn Sekunden drei Fragen beantworten
kann:

1. Was soll ich jetzt tun?
2. Warum genau jetzt oder warum noch nicht?
3. Wo liege ich falsch, wenn ich handle?

Ab dem Zustand `READY LONG` oder `ENTER LONG` muss diese Antwort ohne Wechsel
in ein zweites Skript moeglich sein. Der Wechsel ins Dashboard oder in die
Strategy ist dann eine bewusste Vertiefung, nicht der eigentliche Einstieg.

### Umsetzungsfolge aus Produktsicht

1. Die Core-Sprache und Lite-Hierarchie haerten.
2. Das Dashboard sichtbar von einer zweiten Primaerflaeche zur Companion-
   Surface umpositionieren.
3. Die Strategy als Execution-Wrapper noch klarer dokumentieren und
   positionieren.
4. Erst danach weitere Pro-only-Diagnostik oder C9-Folgeslices an der
   Oberflaechenwahrnehmung ausrichten.

## Konkrete Copy- und Surface-Aenderungen fuer die Mainline

Diese Liste ist die direkte Produktableitung aus dem PM/UX-Review. Sie
beschreibt keine neue Engine-Logik, sondern die sichtbaren Aenderungen, die
den bestehenden Hauptpfad schneller lesbar und sauberer positioniert machen.

### 1. Core: konkrete Lite-Primary-Aenderungen

#### Input-Copy

- `Visual Mode (Lite Hero)` -> `Lite Surface`
- `Show decision detail` -> `Show companion detail`
- `Signal Mode` bleibt erhalten, aber die Tooltip-Eroeffnung soll erst den
  Nutzertradeoff benennen und erst danach die Repaint-/Realtime-Details.
- `User Preset` bleibt der Hauptanker, soll aber in Tooltip und Doku
  konsequent als primaere Lite-Bedienebene beschrieben werden.

#### Hero-Copy

- Die Fuenf-Zeilen-Hierarchie bleibt erhalten.
- `Action:` bleibt unveraendert.
- `Bias:` bleibt unveraendert.
- `Quality:` wird als Vertrauens- und Score-Aussage lesbarer gemacht:
  Zielbild `Trust: Strong | Score 78/100` statt einer komprimierten
  Mischform wie `Strong (78/100)`.
- `Why now:` darf nie auf abstrakte Technikreste oder leere Platzhalter
  hinauslaufen. Jeder Zustand braucht einen klaren Grundsatz:
  Gelegenheit, Blocker oder naechster Trigger.
- `Main risk:` bleibt die explizite Gegenhypothese und ist Pflichtbestandteil
  des Lite-Vertrauensmodells.

#### Lite-Surface-Regeln

- Ab `READY LONG` muessen Trigger und Invalidation ohne Wechsel in ein zweites
  Skript sichtbar sein.
- Lite zeigt keine ungefilterten Technikkuerzel als primaere Botschaft.
- Wenn eine Diagnosebezeichnung noetig ist, kommt erst Klartext und dann
  optional die Kurzform.

### 2. Dashboard: konkrete Pro-Companion-Aenderungen

#### Input- und Header-Copy

- `Surface Mode` bleibt der Schaltername.
- `Compact Detail` -> `Companion Summary`
- `Show Decision Detail` -> `Show Companion Table`
- `Show Trigger/Invalidation` -> `Show Trade Levels`
- Header `SMC Decision Detail` -> `SMC Pro Companion`
- Die Lesart `Compact | Operator bindings hidden` wird auf Companion-Sprache
  gezogen, damit nicht mehr der Eindruck einer zweiten Lite-Surface entsteht.

#### First-Fold-Hierarchie

Die erste sichtbare Companion-Ebene soll nicht primaer als Datentafel lesen,
sondern als Begruendungs- und Blockeroberflaeche. Zielreihenfolge:

1. `Action`
2. `Why Now / Why Blocked`
3. `Risk Plan`
4. `Structure`
5. `Session`
6. `Event Risk`
7. `Data Quality`
8. `Short-term Flow`

Daraus folgen zwei konkrete Copy-Deltas:

- `Short-term Pressure` -> `Short-term Flow`
- die Zeile `Why Now` muss blockerfaehig werden und darf nicht nur eine
  Gelegenheitszeile sein

#### Klartext-vor-Technik-Regel

- `Need confirmed setup`, `Session blocked` und `Signal Quality blocked`
  bleiben Vorbild fuer gute Companion-Sprache.
- Fallback `No reclaim confirmation yet` wird auf eine staerkere Form gezogen:
  `Waiting for reclaim confirmation`.
- Technikkuerzel wie `LTF`, `HTF`, `SD`, `DDVI` und `Vola` duerfen in Pro
  bleiben, aber nur hinter einer lesbaren Klartextzeile.

### 3. Strategy: konkrete Execution-Surface-Aenderungen

#### Wrapper-Copy

- `Entry Mode` -> `Execution Stage`
- `Min Quality Score` -> `Minimum Quality Score`
- `Take Profit R` -> `Take Profit (R)`
- `Use Take Profit` bleibt unveraendert.

#### Surface-Regeln

- Die Strategy bleibt bei genau vier sichtbaren Wrapper-Controls.
- Ihre Rolle wird in Code, Guide und Positionierung explizit als
  `Execution-Surface` formuliert, nicht als Signal-Discovery-Surface.
- `Execution Trigger`, `Execution Invalidation` und `Execution Take Profit`
  bleiben die einzigen sichtbaren Planlinien.
- Die Strategy soll nur dann visuell dominant werden, wenn ein Nutzer bewusst
  in Backtest oder regelgebundene Ausfuehrung wechselt.

### 4. Gemeinsame Sprachregeln fuer alle drei Flaechen

- `WAIT`, `BLOCKED`, `PREPARE LONG`, `READY LONG`, `ENTER LONG` bleiben die
  einzige sichtbare Hauptzustandsleiter.
- Vertrauenssprache wird ueberall identisch verwendet:
  `Strong`, `Usable`, `Thin`, `Provisional`.
- Alert-, Hero-, Dashboard- und Strategy-Sprache sollen denselben Nutzerjob
  spiegeln: entscheiden, verstehen, ausfuehren.

## Priorisiertes Umsetzungs-Backlog mit Ticketzuschnitt

Groessenlogik fuer diese Folgeslices:

- `S` = kleiner Text- oder Surface-Eingriff ohne groessere Verdrahtung
- `M` = sichtbare Mainline-Aenderung mit begleitender Doku oder Testpflege
- `L` = mehrteilige Surface- oder Test-Lane-Aenderung ueber mehrere Dateien

### P0: Hauptpfad sofort lesbarer machen

1. `P0 | M | Core Input- und Hero-Copy haerten`
   Scope: Core-Inputlabels, Tooltips, Hero-Text und Lite-Sprachregeln.
   Hauptdateien: `SMC_Core_Engine.pine`, `docs/TRADINGVIEW_STRATEGY_GUIDE.md`.
   Done wenn: Lite als primaere Surface lesbar ist und die Hero-Texte keine
   primaeren Technikkuerzel mehr tragen.

2. `P0 | M | Core Ready/Enter-Level auf Lite sichern`
   Scope: Trigger- und Invalidation-Sichtbarkeit ab handlungsfaehigem Zustand.
   Hauptdateien: `SMC_Core_Engine.pine`.
   Done wenn: ein Nutzer ab `READY LONG` den Kernplan ohne zweites Skript lesen
   kann.

3. `P0 | M | Dashboard zur Companion-Surface umpositionieren`
   Scope: Surface-Mode-Copy, Header, Toggle-Copy und erste Companion-Hierarchie.
   Hauptdateien: `SMC_Dashboard.pine`, `docs/smc-lite-pro-product-cut.md`.
   Done wenn: das Dashboard nicht mehr wie eine zweite Lite-Surface wirkt.

4. `P0 | S | Strategy als Execution-Surface sprachlich schaerfen`
   Scope: Wrapper-Labels und klare Positionierung im Guide.
   Hauptdateien: `SMC_Long_Strategy.pine`, `docs/TRADINGVIEW_STRATEGY_GUIDE.md`.
   Done wenn: die Strategy sprachlich eindeutig als Backtest- und
   Ausfuehrungsflaeche gelesen wird.

### P1: Companion-Nutzen und Differenzierung verbessern

1. `P1 | M | Dashboard First Fold neu ordnen`
   Scope: sichtbare Reihenfolge der kompakten Companion-Zeilen.
   Hauptdateien: `SMC_Dashboard.pine`.
   Done wenn: die erste Companion-Ebene erst Handlungskontext und dann
   Diagnosebreite zeigt.

2. `P1 | M | Why-now- und Blocker-Sprache vereinheitlichen`
   Scope: Core-Hero, Dashboard-Blocker, Compact-Why-Now und Dynamic Alerts.
   Hauptdateien: `SMC_Core_Engine.pine`, `SMC_Dashboard.pine`.
   Done wenn: Gelegenheit, Wartezustand und Blocker ueberall in derselben
   Nutzerlogik formuliert sind.

3. `P1 | M | Gemeinsamen Sprachcontract fuer Mainline sichern`
   Scope: Zustand, Vertrauen, Risiko- und Surface-Rollen in Code und Docs.
   Hauptdateien: `SMC_Core_Engine.pine`, `SMC_Dashboard.pine`,
   `SMC_Long_Strategy.pine`, `docs/TRADINGVIEW_STRATEGY_GUIDE.md`.
   Done wenn: dieselben Begriffe in Hero, Dashboard, Alerts und Guide exakt
   dieselbe Produktbedeutung tragen.

4. `P1 | S | Strategy-Guide und Hauptpfad-Doku auf Execution-Jobs zuschneiden`
   Scope: Guide-Text, Product-Cut-Doku, eventuell README-Verweise.
   Hauptdateien: `docs/TRADINGVIEW_STRATEGY_GUIDE.md`,
   `docs/smc-lite-pro-product-cut.md`, `README.md`.
   Done wenn: Core, Dashboard und Strategy in der Doku dieselbe Jobverteilung
   tragen wie im Produkt.

### P2: Drift verhindern und Review faelschungssicher machen

1. `P2 | M | UI-Regressionen fuer Produktcopy einfuehren`
   Scope: Tests fuer Surface-Rollen, Header-Copy und zentrale Mainline-Texte.
   Hauptdateien: `tests/test_tradingview_decision_first_ui.py`.
   Done wenn: eine Rueckkehr zu zweideutiger Surface-Sprache automatisch rot
   wird.

2. `P2 | M | Review-Evidence fuer neue Surface-Hierarchie erzeugen`
    Scope: Screenshot- oder Preflight-Evidence fuer Lite, Companion und
    Execution-Surface.
    Hauptdateien: `automation/tradingview/`, `docs/smc-validation-status.md`.
    Done wenn: die Produkt-Hierarchie nicht nur behauptet, sondern mit echter
    Mainline-Evidenz belegbar ist.

### Empfohlene Reihenfolge fuer die Umsetzung

1. Ticket 1
2. Ticket 2
3. Ticket 3
4. Ticket 4
5. Ticket 6
6. Ticket 5
7. Ticket 7
8. Ticket 8
9. Ticket 9
10. Ticket 10

### Abschlussregel fuer diese UX-Folgeslices

Diese Backlog-Welle ist erst dann geschlossen, wenn gleichzeitig gilt:

1. der Core ohne Companion-Skript als klare Lite-Primary-Surface lesbar ist,
2. das Dashboard sprachlich und visuell als Companion statt als zweite
   Primaerflaeche auftritt,
3. die Strategy als Execution-Surface eindeutig positioniert ist,
4. die Hauptzustandsleiter in Core, Dashboard, Strategy und Alerts identisch
   gelesen wird,
5. die wichtigsten UI-Copy-Regeln durch Tests oder Review-Evidence gegen Drift
   abgesichert sind.
