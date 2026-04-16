# Feature Freeze — 15.04.2026 bis 15.05.2026

**Status:** AKTIV  
**Beginn:** 2026-04-15  
**Ende:** 2026-05-15 (30 Tage)  
**Autorität:** Owner Review v3  
**Freeze-Basis:** sauber (2026-04-16, 4685 tests grün, 0 Failures, BUS-Binding 67/67 verifiziert)

---

## Erlaubt

- Bugfixes (jede Schwere)
- Pipeline-Reparatur und -Optimierung
- Test-Erweiterung
- Dokumentations-Verbesserung
- Performance-Optimierung
- Monitoring-Verbesserung
- Integration bestehender Enrichment-Module (Treasury, Short Interest, Sector Rotation, Institutional, Analyst, Insider)

## NICHT erlaubt

- Neue Enrichment-Module (über die bestehenden 6 hinaus)
- Neue Alertconditions (über die bestehenden 10 hinaus)
- Neue Pine-Funktionen (State-Transitions, Zone-Typen, etc.)
- Neue Library-Felder (über bestehende + Enrichment-Felder hinaus)
- Neue UI-Elemente (über Hero Card / Dashboard hinaus)
- Neue Inputs (über die bestehenden 308 hinaus)

## Exit-Kriterien (alle erforderlich)

- [ ] Library-Pipeline 14+ Tage stabil (56+ erfolgreiche Refreshs)
- [ ] 2+ Measurement-Benchmark-Reports existieren
- [ ] End-to-End Smoke-Test bestanden (Bewertung ≥ 7/10)
- [ ] 21 fehlende Library-Felder adressiert
- [ ] Pine-Titel korrekt ("SMC Long-Dip Suite v7")
- [ ] Kein kritischer Bug offen

## Ausnahmen

Ausnahmen erfordern explizite Owner-Genehmigung mit dokumentierter Begründung.

## After-Freeze Feature-Requests

_Feature-Requests werden hier gesammelt, nicht implementiert._

1. _(leer)_
