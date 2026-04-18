# Post-WP21 Review Freeze — Beobachtungsphase

Stand: 2026-04-18 (WP-26)

## Zweck

Das System ist nach WP-9 bis WP-21 an einem Punkt, an dem weitere
Verbesserungswellen leicht mehr Schaden durch Scope-Aufweitung als Nutzen
bringen können. Dieses Dokument definiert die Regeln für die
Beobachtungsphase nach dem Engineering-Programm.

---

## Erlaubte Änderungen während der Beobachtungsphase

| Typ | Erlaubt? | Beispiel |
|-----|----------|---------|
| Echter Bugfix | ✅ Ja | Laufzeitfehler in Produktion, Testfailure |
| Governance-/Evidence-Nachschärfung | ✅ Ja | Freeze-Exit-Evidenz nachtragen |
| Dokumentations-Klarstellung | ✅ Ja | Runbook-Korrektur, Tippfehler |
| Admin-/Runbook-Schritte | ✅ Ja | Branch-Protection-Aktivierung |
| CI-Config-Fix | ✅ Ja | Coverage-Threshold, Workflow-YAML |
| Dependency-Update (Security) | ✅ Ja | Nur bei CVE oder Advisory |

## Nicht erlaubte Änderungen

| Typ | Erlaubt? | Begründung |
|-----|----------|-----------|
| Neue Feature-Welle | ❌ Nein | Scope-Ausweitung |
| Breiter Refactor ohne Defekt | ❌ Nein | Risiko ohne akuten Anlass |
| Neue Surface-/UX-Expansion | ❌ Nein | Produktidentität ist frozen (WP-21) |
| Neue Provider-Integration | ❌ Nein | Kein akuter Bedarf |
| Schwellenwert-Absenkungen | ❌ Nein | Grünfärbung |
| Neue Metrik-Familien | ❌ Nein | Komplexitätswachstum |
| Pine-Logik-Änderungen | ❌ Nein | Nur via Bugfix-Pfad |

---

## Trigger für neues Engineering-Programm

Ein neues größeres Engineering-Programm ist erst zulässig, wenn:

1. **Freeze-Exit vollzogen** — der Operator Pack (WP-24) wurde vollständig
   durchlaufen und der Owner hat den Exit bestätigt.
2. **14-Tage-Stabilität nachgewiesen** — die Pipeline-Kriterien aus
   `docs/freeze_exit_stability_criteria.md` §2 sind erfüllt.
3. **Neue fachliche Anforderung** — es gibt einen dokumentierten, neuen
   Anlass (nicht Restarbeit aus dem bestehenden Blueprint).
4. **Owner-Freigabe** — keine autonome Wiederaufnahme ohne explizite
   Entscheidung.

---

## Anti-Patterns

Diese Muster sollen bewusst vermieden werden:

- **"Noch schnell verbessern"** — nach 21 WPs ist das System reif genug.
  Jede Verbesserung muss den Beobachtungszyklus respektieren.
- **"Feature als Bugfix tarnen"** — ein echtes Bugfix behebt einen
  reproduzierbaren Defekt, nicht eine fehlende Funktion.
- **"Doku-Expansion als Klarstellung"** — neue Konzepte oder Architekturen
  sind keine Klarstellungen. Klarstellungen korrigieren bestehende Aussagen.
- **"Schwelle anpassen statt fixen"** — wenn ein Gate rot ist, liegt das
  Problem beim System, nicht beim Gate.

---

## Dauer

Die Beobachtungsphase dauert mindestens bis zum Freeze-Exit-Vollzug
(frühestens 2026-04-29, geplant spätestens 2026-05-15). Danach entscheidet
der Owner über die Dauer der Post-Exit-Beobachtung.

---

## Referenzen

| Dokument | Bezug |
|----------|-------|
| `docs/freeze_exit_stability_criteria.md` | Stabilitätskriterien |
| `docs/engineering-program/freeze_exit_operator_pack.md` | Exit-Day-Prozess |
| `docs/SMC_PRODUCT_IDENTITY.md` | Produkt-Freeze (WP-21) |
| `docs/engineering-program/end_state_evidence_bundle.md` | Endzustand-Nachweis |
