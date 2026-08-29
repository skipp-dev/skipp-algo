"""Der Urteiler liest ein JOB-LOG, nicht rohe stdout.

Warum es diesen File gibt
=========================

Die erste Fassung von ``scripts/proof_judges/runner_label_variable_watch.py``
(#5178) verankerte ihre Zeilen-Regex auf ``^``. Im GitHub-Job-Log traegt aber
jede Zeile ein Praefix aus Job-Name, Step-Name und Zeitstempel::

    watch	Arm-Runner-Label ...	2026-08-29T07:19:00.0787594Z | `SMC_CI_ARM_RUNNER` | ...

Kopfzeile und Umfangszeile wurden unverankert gesucht und matchten sauber —
nur die Urteilszeilen nie. Der Urteiler haette also **jeden gesunden Lauf** als
``rows_missing`` angeklagt, und zwar mit einer plausibel klingenden Begruendung
("fuer mindestens eine Variable fiel kein Urteil"). Eine falsche Anschuldigung,
die wie ein echter Befund aussieht, ist teurer als gar kein Urteil.

Gefunden wurde das nicht durch Nachdenken, sondern indem der Urteiler gegen die
Ausgabe des ersten echten Laufs auf ``main`` (33240542676) gehalten wurde. Die
Unit-Tests in ``tests/test_check_runner_label_variables.py`` konnten es nicht
sehen: sie fuettern die rohe stdout der Sonde, also genau das Format, in dem die
Verankerung stimmt.

Dieser File pinnt deshalb die Eigenschaft, an der es lag: **Praefix-Toleranz**.
"""

from __future__ import annotations

from scripts.proof_judges import corpus_for, load_judge

_JUDGE = "runner_label_variable_watch"

#: Ein Job-Log-Ausschnitt in der Form, die ``gh run view --log`` liefert.
#: Von Hand notiert statt aus dem Korpus gelesen: ein Test, der sein
#: Eingabeformat aus dem Pruefling zieht, kann einen Formatwechsel nicht sehen.
_JOB_LOG = (
    "watch\tRunner-Variablen gegen die Allowlist halten\t2026-08-29T07:19:00.0Z ## runner-label-variable-watch\n"
    "watch\tRunner-Variablen gegen die Allowlist halten\t2026-08-29T07:19:00.0Z \n"
    "watch\tRunner-Variablen gegen die Allowlist halten\t2026-08-29T07:19:00.0Z "
    "Geprueft: 2 variablengesteuerte `runs-on`-Variablen ueber 71 Workflow-Dateien.\n"
    "watch\tRunner-Variablen gegen die Allowlist halten\t2026-08-29T07:19:00.0Z \n"
    "watch\tRunner-Variablen gegen die Allowlist halten\t2026-08-29T07:19:00.0Z "
    "| Variable | Wert | Lanes | Urteil |\n"
    "watch\tRunner-Variablen gegen die Allowlist halten\t2026-08-29T07:19:00.0Z |---|---|---|---|\n"
    "watch\tRunner-Variablen gegen die Allowlist halten\t2026-08-29T07:19:00.0Z "
    "| `SMC_CI_ARM_RUNNER` | `ubuntu-24.04-arm` | 1 | OK |\n"
    "watch\tRunner-Variablen gegen die Allowlist halten\t2026-08-29T07:19:00.0Z "
    "| `SMC_GH_HOSTED_RUNNER` | `ubuntu-latest` | 71 | OK |\n"
    "watch\tRunner-Variablen gegen die Allowlist halten\t2026-08-29T07:19:00.0Z Token-Quelle: `GITHUB_TOKEN`.\n"
)


def test_judge_reads_rows_through_the_job_log_prefix() -> None:
    verdict = load_judge(_JUDGE).judge({"log": _JOB_LOG}, None)
    assert verdict.state == "PASS", (
        f"gesunder Lauf als {verdict.state}/{verdict.branch} beurteilt: {verdict.detail}"
    )
    assert verdict.branch == "scope_measured_and_judged"
    assert "SMC_GH_HOSTED_RUNNER" in verdict.detail, (
        "das Urteil nennt die beurteilten Variablen nicht — dann sagt ein PASS nicht, "
        "WORUEBER es urteilt"
    )


def test_the_header_row_alone_is_not_mistaken_for_a_verdict_row() -> None:
    """Gegenprobe zur Lockerung: die Regex darf nicht alles Rohrfoermige fressen.

    Ohne die Backtick-Pflicht wuerden Kopf- und Trennzeile als Urteilszeilen
    zaehlen — dann waere `rows_missing` nie erreichbar und der Schutz weg.
    """
    header_only = (
        "watch\tstep\t2026-08-29T07:19:00.0Z "
        "Geprueft: 2 variablengesteuerte `runs-on`-Variablen ueber 71 Workflow-Dateien.\n"
        "watch\tstep\t2026-08-29T07:19:00.0Z | Variable | Wert | Lanes | Urteil |\n"
        "watch\tstep\t2026-08-29T07:19:00.0Z |---|---|---|---|\n"
    )
    verdict = load_judge(_JUDGE).judge({"log": header_only}, None)
    assert verdict.state == "FAIL"
    assert verdict.branch == "rows_missing", (
        f"Kopf-/Trennzeile wurde als Urteilszeile gezaehlt: {verdict.branch}"
    )


def test_the_recorded_corpus_is_a_real_run_and_reaches_pass() -> None:
    """Positivkontrolle: der Korpus ist echt und traegt das Urteil.

    Ohne diese Zeile koennte der Korpus leer sein und alle Aussagen darueber
    waeren vakuum.
    """
    corpus = corpus_for(_JUDGE)
    assert corpus, f"kein Korpus fuer {_JUDGE} aufgezeichnet"
    judge = load_judge(_JUDGE)
    for run_id, evidence in corpus:
        assert run_id.isdigit(), f"Korpus {run_id!r} sieht nicht nach einer echten Run-ID aus"
        log = evidence.get("log", "") if isinstance(evidence, dict) else ""
        assert "\t" in log, (
            f"Korpus {run_id} traegt keine Job-Log-Praefixe — dann ist es rohe stdout "
            "und pinnt genau das Format nicht, an dem #5178 scheiterte"
        )
        verdict = judge.judge(evidence, None)
        assert verdict.state == "PASS", (
            f"aufgezeichneter echter Lauf {run_id} wird als {verdict.state}/"
            f"{verdict.branch} beurteilt: {verdict.detail}"
        )
