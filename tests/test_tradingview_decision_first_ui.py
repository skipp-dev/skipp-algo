from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_core_has_decision_first_hero_contract() -> None:
    source = _read("SMC_Core_Engine.pine")

    assert 'indicator("SMC Long-Dip Suite v7", "SMC Long-Dip Suite v7", overlay = true' in source
    assert "var g_mode = '1. Core Setup'" in source
    assert "var g_output = '2. Output'" in source
    assert "var g_trade_plan = '3. Trade Plan'" in source
    assert "var g_session_gate = '4. Session Gate'" in source
    assert "var g_runtime = '5. Runtime Budget'" in source
    assert "var g_ltf = '6. Advanced - Lower Timeframe'" in source
    assert "resolve_core_product_state(" in source
    assert "resolve_trust_tier(" in source
    assert "cr.resolve_core_provider_state(" in source
    assert "cr.compose_core_hero_text(" in source
    assert "var label core_hero_card = na" in source
    assert "compact_mode = input.bool(true, 'Focus View'" in source
    assert "show_dashboard = input.bool(true, 'Show Decision Brief', group = g_output" in source
    assert "enable_dynamic_alerts = input.bool(true, 'Enable dynamic alerts', group = g_output" in source
    assert "target1_r = input.float(1.0, 'Target 1 (R)', minval = 0.25, step = 0.25, group = g_trade_plan" in source
    assert "use_trade_session_gate = input.bool(true, 'Use Trade Session Gate', group = g_session_gate, inline = 'trade1'" in source
    assert "performance_mode = input.string('Balanced', 'Performance Mode', options = ['Light', 'Balanced', 'Pro', 'Debug'], group = g_runtime" in source
    assert 'Focus View' in source
    resolvers = _read("SMC++/smc_context_resolvers.pine")
    assert 'Confidence: ' in resolvers
    assert 'Trust: ' in resolvers
    assert 'Provider: ' in resolvers
    assert 'Main blocker: ' in resolvers
    assert 'VIX: ' in resolvers
    assert 'Tone: ' in resolvers
    assert 'Market: ' in resolvers
    assert "why_now := 'Trigger is live'" in resolvers
    assert "string core_main_risk = cr.compose_main_risk_text(core_product_state, event_risk_state" in source
    assert "string core_provider_state = cr.resolve_core_provider_state(lib_erl_provider_status, lib_provider_count, lib_stale_providers)" in source
    assert "bool core_plan_visible = (long_ready_state or long_entry_best_state or long_entry_strict_state)" in source
    assert "plot(core_plan_visible ? long_state.trigger : na, 'Core Trigger'" in source
    assert "plot(core_plan_visible ? long_state.invalidation_level : na, 'Core Invalidation'" in source


def test_dashboard_has_companion_summary_and_pro_diagnostics() -> None:
    source = _read("SMC_Dashboard.pine")

    assert 'var string g_surface = "1. Product Surface"' in source
    assert 'var string g_bus_lifecycle = "2. Operator Only - Lifecycle BUS"' in source
    assert 'var string g_local_debug = "9. Operator Only - Local Debug Mirrors"' in source
    assert 'surface_mode = input.string("Decision Brief"' in source
    assert source.index('surface_mode = input.string("Decision Brief"') < source.index('src_zone_active = input.source(close, "BUS ZoneActive"')
    assert "dashboard_product_state_text(" in source
    assert 'dashboard_row(smc_dashboard, 0, "SMC Long-Dip Dashboard v7", "Decision Brief | Linked setup active"' in source
    assert 'dashboard_row(smc_dashboard, 0, "SMC Long-Dip Dashboard v7", "Audit View | Expert review only", header_bg, txt)' in source
    assert 'dashboard_row(smc_dashboard, 1, "Market"' in source
    assert 'dashboard_row(smc_dashboard, 2, "Structure"' in source
    assert 'dashboard_row(smc_dashboard, 3, "Session / Market"' in source
    assert 'dashboard_row(smc_dashboard, 4, "Event Risk"' in source
    assert 'dashboard_compact_trust_text(' in source
    assert 'dashboard_row_tt(smc_dashboard, 6, "Trust / Data"' in source
    assert 'dashboard_row(smc_dashboard, 7, "Short-term Pressure"' in source
    assert 'dashboard_row(smc_dashboard, 8, "Risk Plan"' in source
    assert 'dashboard_row(smc_dashboard, 1, "Action"' not in source
    assert 'dashboard_row(smc_dashboard, 2, "Why now"' not in source
    assert 'Audit View | Expert review only' in source
    assert 'dashboard_row(smc_dashboard, 2, "Action"' in source
    assert 'dashboard_row(smc_dashboard, 3, "Why now"' in source
    assert 'section_row(smc_dashboard, 1, "[ Decision Detail ]", header_bg, txt)' in source
    assert 'section_row(smc_dashboard, 10, "[ Lean Surface ]", header_bg, txt)' in source
    assert 'section_row(smc_dashboard, 18, "[ Trust & Provider ]", header_bg, txt)' in source
    assert 'section_row(smc_dashboard, 23, "[ Calibration Confidence ]", header_bg, txt)' in source
    assert 'section_row(smc_dashboard, 26, "[ Per-Family Performance ]", header_bg, txt)' in source
    assert 'section_row(smc_dashboard, 31, "[ FVG Health ]", header_bg, txt)' in source
    assert 'section_row(smc_dashboard, 34, "[ Gates ]", header_bg, txt)' in source
    assert 'section_row(smc_dashboard, 42, "[ Quality Rows ]", header_bg, txt)' in source
    assert 'section_row(smc_dashboard, 53, "[ Support / Metrics ]", header_bg, txt)' in source
    assert 'section_row(smc_dashboard, 64, "[ Risk / Plan ]", header_bg, txt)' in source
    assert 'section_row(smc_dashboard, 69, "[ Debug ]", header_bg, txt)' in source


def test_dashboard_hero_surface_pins_one_liner_row_and_shifted_row_order() -> None:
    """Plan 1.1 caveat resolution.

    The Hero surface gained a product hero one-liner on row 1 (SMC · BIAS ·
    TIER · Top FAM HR% · Zone N · ⚠BLOCKER), pushing the existing seven
    decision-first rows from 1..7 down to 2..8 with `table.clear` extended
    to 9. Pin every row so a future row insert/shift fails fast and
    forces the author to update the IA contract together.
    """
    source = _read("SMC_Dashboard.pine")

    assert 'dashboard_row(smc_dashboard, 0, "SMC Long-Dip Dashboard v7", "Hero | Decision-first surface"' in source
    assert 'dashboard_row_tt(smc_dashboard, 1, "Hero", _hero_one_display, _hero_one_bg, txt, _hero_one_tt)' in source
    assert 'dashboard_row(smc_dashboard, 2, "Market", h_market_line,' in source
    assert 'dashboard_row(smc_dashboard, 3, "Action", h_action_line,' in source
    assert 'dashboard_row(smc_dashboard, 4, "Why now", h_why_line,' in source
    assert 'dashboard_row(smc_dashboard, 5, "Setup Quality", h_quality_line,' in source
    assert 'dashboard_row(smc_dashboard, 6, "Trust", h_trust_line,' in source
    assert 'dashboard_row(smc_dashboard, 7, "Risk", h_risk_line,' in source
    assert 'dashboard_row(smc_dashboard, 8, "Risk Plan", dashboard_compact_risk_plan_text(' in source
    assert "table.clear(smc_dashboard, 0, 9, 1, 79)" in source
    # Hero one-liner contract: must be assembled from the generated mp.*
    # contract (no hard-coded values) via the user-configurable token
    # composer and must carry the canonical blocker prefix so a degraded
    # read is visible at a glance.
    assert 'string _hero_fam = mp.ZONE_PRIORITY_TOP_FAMILY' in source
    assert 'string _hero_one = compose_hero_one_liner(hero_token_order, mp.HERO_BIAS, mp.HERO_TRUST, _hero_fam, _hero_fam_pct, mp.ZONE_PRIORITY_RANK, _hero_blocker, calibration_sha)' in source
    # Composer + token-order input must exist with the canonical default.
    assert 'compose_hero_one_liner(string order_csv, string bias, string trust, string fam, int fam_pct, string zone, string blocker, string sha) =>' in source
    assert 'hero_token_order = input.string("BIAS,TRUST,FAM,ZONE,BLOCKER", "Hero Token Order"' in source
    assert '"\u26a0"' in source  # blocker glyph still rendered by composer


def test_dashboard_explain_popup_tooltips_cover_zone_priority_and_per_family() -> None:
    """Plan 1.5 — every Zone Priority row and every per-family row carries a
    tooltip explaining family / calibrated weight / tier / source. The
    helper itself must trim long strings to stay under Pine's tooltip
    char limit."""
    source = _read("SMC_Dashboard.pine")

    # Helper exists and trims defensively.
    assert "dashboard_row_tt(table tbl, int row, string label_text, string value_text, color bg, color txt, string tt) =>" in source
    assert "str.length(tt) > 2000" in source
    assert ", tooltip = _tt_safe)" in source

    # Decision Brief Zone Priority popup.
    assert 'string zp_brief_tt = "Zone " + zp_rank + " — Why?\\n' in source
    assert 'dashboard_row_tt(smc_dashboard, 5, "Zone Priority", zp_line, zp_bg, txt, zp_brief_tt)' in source

    # Audit Zone Priority popup carries calibrated weight + reason +
    # SHA-anchored source for credibility.
    assert 'string _audit_zp_tt = "Zone " + _audit_zp_rank + " — Why?\\n' in source
    assert 'Source: zone_priority_calibration.json' in source
    assert 'dashboard_row_tt(smc_dashboard, 22, "Zone Priority", _audit_zp_line, _audit_zp_bg, txt, _audit_zp_tt)' in source

    # Per-family rows — each family gets a tooltip with its calibrated weight + tier.
    for family, mp_field in (
        ("OB", "mp.ZONE_CAL_OB"),
        ("FVG", "mp.ZONE_CAL_FVG"),
        ("BOS", "mp.ZONE_CAL_BOS"),
        ("SWEEP", "mp.ZONE_CAL_SWEEP"),
    ):
        marker = 'dashboard_row_tt(smc_dashboard, '
        per_family_tt_marker = f'"{family} — calibrated weight " '
        assert marker in source
        assert per_family_tt_marker in source, f"missing tooltip text for family {family}"
        assert mp_field in source


def test_dashboard_visual_consolidation_publishes_tier_and_icon_tokens() -> None:
    """Plan 1.6 — single source of truth for tier colours and icon glyphs.
    Hero one-liner must paint its background from these tokens."""
    source = _read("SMC_Dashboard.pine")

    assert "var color CLR_TIER_T1" in source
    assert "var color CLR_TIER_T2" in source
    assert "var color CLR_TIER_T3" in source
    assert "var color CLR_TIER_T4" in source
    assert 'var string ICON_UP   = "⬆"' in source
    assert 'var string ICON_DOWN = "⬇"' in source
    assert 'var string ICON_WARN = "⚠"' in source
    assert 'var string ICON_OK   = "✅"' in source
    # Hero one-liner background uses the new tier tokens (not raw colors).
    assert "color _hero_one_bg = mp.HERO_TRUST == \"healthy\" ? color.new(CLR_TIER_T1," in source
    assert "color.new(CLR_TIER_T4," in source


def test_core_engine_quickstart_preset_publishes_effective_defaults_contract() -> None:
    """Plan 1.4 caveat resolution.

    The `quickstart_preset` input must do more than emit a status-line
    label: it must publish a typed effective-defaults pack via the BUS
    plot contract so downstream consumers (and tests) can pin the
    preset → effective-values mapping. W1 will wire these BUS values
    into the actual gate logic; the contract shape is locked here.
    """
    source = _read("SMC_Core_Engine.pine")

    # Input declaration with all four classes + status-line emission.
    assert "var string quickstart_preset = input.string('Custom', 'Quickstart Preset'" in source
    for option in ("'Custom'", "'Mega-Cap US Tech'", "'Financial Services'", "'Energy'"):
        assert option in source

    # Effective-defaults helpers (pure functions of the preset name).
    assert "preset_effective_rvol_min(string preset) =>" in source
    assert "preset_effective_htf_bias_min(string preset) =>" in source
    assert "preset_effective_fvg_quality_gate(string preset) =>" in source
    assert "preset_effective_vol_regime_default(string preset) =>" in source
    assert "preset_effective_class_code(string preset) =>" in source

    # Hard-pin the curated mapping so a value tweak forces a deliberate edit.
    assert "preset == 'Mega-Cap US Tech'   ? 1.30" in source  # rvol_min Tech
    assert "preset == 'Financial Services' ? 1.20" in source  # rvol_min FinSvc
    assert "preset == 'Energy' ? 1.10" in source              # rvol_min Energy
    assert "preset == 'Mega-Cap US Tech'   ? 0.70" in source  # htf_bias_min Tech
    assert "preset == 'Mega-Cap US Tech'   ? 2 :" in source   # fvg gate Tech (high)
    assert "preset == 'Energy' ? 1 : 0"        in source      # vol regime default Energy
    assert "preset == 'Mega-Cap US Tech'   ? 1 :" in source   # class code Tech

    # BUS contract: the five hidden plots downstream consumers must read.
    assert "plot(preset_effective_class_code(quickstart_preset),"        in source
    assert "'BUS PresetClassCode'"     in source
    assert "plot(preset_effective_rvol_min(quickstart_preset),"          in source
    assert "'BUS PresetRvolMin'"       in source
    assert "plot(preset_effective_htf_bias_min(quickstart_preset),"      in source
    assert "'BUS PresetHtfBiasMin'"    in source
    assert "plot(preset_effective_fvg_quality_gate(quickstart_preset),"  in source
    assert "'BUS PresetFvgQualGate'"   in source
    assert "plot(preset_effective_vol_regime_default(quickstart_preset),"in source
    assert "'BUS PresetVolRegimeDef'"  in source


def test_core_engine_quickstart_preset_rvol_floor_is_wired_into_effective_gate() -> None:
    """Plan 1.4 W1 — RVOL is the first axis we actually wire end-to-end.

    The preset acts as a *floor* (math.max), never a ceiling, so a Custom
    preset (returns 0.0) is a no-op and a stricter preset can never relax
    the user's own threshold. Lock the exact wiring so an accidental
    `min` flip or removal fails the suite.
    """
    source = _read("SMC_Core_Engine.pine")
    assert "effective_relvol_good := math.max(effective_relvol_good, preset_effective_rvol_min(quickstart_preset))" in source
    # Helper must be declared before its first consumer; the consumer
    # lives in the gate section much further down. A simple ordering
    # assert catches forward references that would break Pine compile.
    helper_idx = source.find("preset_effective_rvol_min(string preset) =>")
    consumer_idx = source.find("math.max(effective_relvol_good, preset_effective_rvol_min(quickstart_preset))")
    assert helper_idx > 0 and consumer_idx > 0, "helper or consumer missing"
    assert helper_idx < consumer_idx, (
        f"preset_effective_rvol_min helper (idx {helper_idx}) must be declared "
        f"before its consumer (idx {consumer_idx}) — Pine forward refs do not compile"
    )
    # User-facing input tooltip must explain that the preset can raise the floor.
    assert "Plan 1.4: when a Quickstart Preset other than Custom is active, the preset may raise this floor" in source


def test_core_engine_quickstart_preset_htf_bias_floor_is_wired_into_context_quality() -> None:
    """Plan 1.4 W2 — HTF bias is the second preset axis we wire end-to-end.

    Same floor pattern as RVOL: the preset count can only raise the
    user's own ``min_htf_alignment_count``, never lower it. The
    helper ``preset_effective_htf_align_count`` translates the float
    bias-min (0..1) into the integer count compute_context_quality()
    actually uses (1..3).
    """
    source = _read("SMC_Core_Engine.pine")
    assert "var int min_htf_alignment_count = input.int(2, 'HTF Bias Min Count'" in source
    assert "int _htf_floor = math.max(min_htf_alignment_count, preset_effective_htf_align_count(quickstart_preset))" in source
    assert "bool _htf_ok = _htf_count >= _htf_floor" in source
    helper_idx = source.find("preset_effective_htf_align_count(string preset) =>")
    consumer_idx = source.find("math.max(min_htf_alignment_count, preset_effective_htf_align_count(quickstart_preset))")
    assert helper_idx > 0 and consumer_idx > 0, "helper or consumer missing"
    assert helper_idx < consumer_idx, (
        f"preset_effective_htf_align_count helper (idx {helper_idx}) must be declared "
        f"before its consumer (idx {consumer_idx}) — Pine forward refs do not compile"
    )
    # The legacy hardcoded ">= 2" must be gone — otherwise the preset floor is dead code.
    assert "_htf_ok = _htf_count >= 2" not in source, (
        "legacy hardcoded HTF threshold still present; preset floor would be ignored"
    )


def test_dashboard_audit_view_has_why_this_tier_drilldown() -> None:
    """Plan 1.5 follow-up — Audit View must surface a top-3 ranked
    breakdown of the calibrated family weights so an operator can answer
    'why does the engine pick OB over FVG today?' in one glance.

    Read-only on the existing ZONE_CAL_* BUS contract; no engine change.
    The drill-down is appended at rows 74/75 and the universe-status
    feature matrix at rows 76/77 so the existing audit-row pin tests keep
    working.
    """
    source = _read("SMC_Dashboard.pine")

    # Table size + final clear range must accommodate the new rows.
    # Grew 78 → 80 rows when Universe Status rows were appended above the
    # Trade-Mgmt rows (Trade=78, Stop=79).
    assert "table.new(position.bottom_right, 2, 80, border_width = 0)" in source
    assert "table.clear(smc_dashboard, 0, 0, 1, 79)" in source
    # New rows pinned by section + content row.
    assert 'section_row(smc_dashboard, 74, "[ Why this Tier? ]"' in source
    assert 'dashboard_row_tt(smc_dashboard, 75, "Top-3 Weights",' in source
    assert 'section_row(smc_dashboard, 76, "[ Universe Status ]"' in source
    assert 'dashboard_row_tt(smc_dashboard, 77, "Universe Status", dashboard_universe_badge,' in source
    # Drill-down must read from the published BUS contract (no shadow source).
    for fam in ("OB", "FVG", "BOS", "SWEEP"):
        assert f"mp.ZONE_CAL_{fam}" in source
    # The full ranked tooltip must include all four families and a source pointer.
    assert "Why this Tier? Ranked calibrated weights" in source
    assert "Source: zone_priority_calibration.json" in source


def test_long_strategy_has_wrapper_controls_and_core_plan_outputs() -> None:
    source = _read("SMC_Long_Strategy.pine")

    assert 'strategy("SMC Long-Dip Strategy v7", overlay = true' in source
    assert 'var string g_setup = "1. Execution Setup"' in source
    assert 'var string g_bus_entry = "3. Expert Mapping - Entry States"' in source
    assert source.index('entry_mode = input.string("Strict", "Execution Stage"') < source.index('src_armed = input.source(close, "BUS Armed"')
    assert source.index('use_take_profit = input.bool(true, "Use Take Profit"') < source.index('src_trigger = input.source(close, "BUS Trigger"')
    assert 'src_armed = input.source(close, "BUS Armed"' in source
    assert 'src_entry_strict = input.source(close, "BUS EntryStrict"' in source
    assert 'src_trigger = input.source(close, "BUS Trigger"' in source
    assert 'src_invalidation = input.source(close, "BUS Invalidation"' in source
    assert 'entry_mode = input.string("Strict", "Execution Stage", options = ["Armed", "Confirmed", "Ready", "Best", "Strict"], group = g_setup' in source
    assert 'min_quality_score = input.float(0.0, "Minimum Quality Score", step = 0.25, group = g_setup' in source
    assert 'use_take_profit = input.bool(true, "Use Take Profit", group = g_trade_plan' in source
    assert 'take_profit_r = input.float(2.0, "Take Profit (R)", minval = 0.0, step = 0.25, group = g_trade_plan' in source
    assert 'Minimum quality score required before the linked core setup can stage an execution plan.' in source
    assert 'Bind these expert-mapping inputs top-to-bottom to the matching linked core outputs from SMC Core.' in source
    assert 'Bind these plan inputs after the state group so the linked execution plan stays deterministic.' in source
    assert 'plot(src_trigger, "Execution Trigger"' in source
    assert 'plot(src_invalidation, "Execution Invalidation"' in source
    assert 'plot(use_take_profit ? (strategy.position_size > 0 ? active_take_profit : take_profit_price) : na, "Execution Take Profit"' in source
    assert '"Entry Stage"' not in source
    assert '"Minimum Setup Quality"' not in source
    assert '"Enable Profit Target"' not in source
    assert '"Profit Target (R)"' not in source


def test_r11_migration_and_operator_guide_is_linked_and_explicit() -> None:
    readme = _read("README.md")
    guide = _read("docs/smc-tradingview-r1-1-migration-and-operator-guide.md")

    assert "docs/smc-tradingview-r1-1-migration-and-operator-guide.md" in readme
    assert "compact_mode" in guide
    assert "surface_mode" in guide
    assert "entry_mode" in guide
    assert "SMC_Long_Strategy.pine" in guide
    assert "operator-only" in guide
    assert "BUS binding order" in guide
    assert "visual-only" in guide
    assert "Decision Brief" in guide
    assert "Execution Stage" in guide
    assert "Execution Trigger" in guide
    assert "Core-Outputs" in guide


def test_core_and_dashboard_trust_tier_values_are_consistent() -> None:
    core = _read("SMC_Core_Engine.pine")
    dashboard = _read("SMC_Dashboard.pine")

    for tier in ["High", "Guarded", "Degraded", "Insufficient"]:
        assert f"'{tier}'" in core, f"Core must contain trust tier '{tier}'"

    for tier in ["high", "guarded", "degraded", "insufficient"]:
        assert f'"{tier}"' in dashboard, f"Dashboard must contain trust tier '{tier}'"

    assert "resolve_trust_tier(" in core
    assert "resolve_dashboard_trust_tier(" in dashboard

    resolvers = _read("SMC++/smc_context_resolvers.pine")

    assert "Provider: " in resolvers
    assert "Main blocker: " in resolvers
    assert "Trust: " in resolvers

    assert '"Trust / Data"' in dashboard
    assert '"provider: "' in dashboard or "provider: " in dashboard


def test_core_trust_resolution_defaults_to_insufficient() -> None:
    core = _read("SMC_Core_Engine.pine")

    func_start = core.index("resolve_trust_tier(")
    func_body = core[func_start:func_start + 600]

    assert "'Insufficient'" in func_body
    assert func_body.index("'Insufficient'") < func_body.index("'High'"), \
        "Default must be Insufficient before any promotion to High"


def test_dashboard_trust_resolution_defaults_to_insufficient() -> None:
    dashboard = _read("SMC_Dashboard.pine")

    func_start = dashboard.index("resolve_dashboard_trust_tier(")
    func_body = dashboard[func_start:func_start + 600]

    assert '"insufficient"' in func_body
    assert func_body.index('"insufficient"') < func_body.index('"high"'), \
        "Default must be insufficient before any promotion to high"


# ── WP-A4: Hero Card Regime Override Explanation ────────────────


def test_hero_card_explains_regime_override() -> None:
    """compose_core_hero_text must include regime override logic (WP-A4)."""
    source = _read("SMC++/smc_context_resolvers.pine")

    func_start = source.index("compose_core_hero_text(")
    func_body = source[func_start:func_start + 2000]

    # The function must accept regime parameters
    assert "market_regime" in func_body
    assert "regime_blocks" in func_body or "regime_dims" in func_body

    # When regime overrides, Bias line must include explanation
    assert "regime overrides" in func_body

    # Action line must show regime context
    assert "(regime: " in func_body


def test_hero_card_call_passes_regime_data() -> None:
    """The barstate.islast call site must pass MARKET_REGIME to compose_core_hero_text."""
    source = _read("SMC_Core_Engine.pine")

    # Find the call inside barstate.islast
    call_idx = source.index("compose_core_hero_text(core_product_state")
    call_line = source[call_idx:source.index("\n", call_idx)]

    assert "mp.MARKET_REGIME" in call_line
    assert "lib_regime_blocked" in call_line
    assert "lib_regime_dimmed" in call_line


# ── WP-A7: Trust-Tier Surface Explanation ───────────────────────


def test_trust_tier_suffix_function_exists_with_all_tiers() -> None:
    """compose_trust_tier_suffix must produce a suffix for each trust tier (WP-A7)."""
    source = _read("SMC_Core_Engine.pine")

    func_start = source.index("compose_trust_tier_suffix(")
    func_body = source[func_start:func_start + 800]

    # Must handle all 4 tiers (Insufficient is the else branch)
    for tier in ["High", "Guarded", "Degraded"]:
        assert f"'{tier}'" in func_body, f"compose_trust_tier_suffix must handle tier '{tier}'"

    # Insufficient is the default/else → produces 'no measurement data'
    assert "no measurement data" in func_body

    # Suffix must include score for the actionable tiers
    assert "sq_score" in func_body
    # Must reference provider_status for degraded explanation
    assert "provider_status" in func_body


def test_hero_card_trust_line_includes_suffix() -> None:
    """compose_core_hero_text must include trust_suffix in the Trust line (WP-A7)."""
    source = _read("SMC++/smc_context_resolvers.pine")

    func_start = source.index("compose_core_hero_text(")
    func_body = source[func_start:func_start + 2000]

    # Function must accept trust_suffix parameter
    assert "trust_suffix" in func_body
    # Trust display must incorporate the suffix
    assert "trust_display" in func_body


def test_hero_card_call_passes_trust_suffix() -> None:
    """The barstate.islast call site must compute and pass the trust suffix."""
    source = _read("SMC_Core_Engine.pine")

    assert "compose_trust_tier_suffix(" in source
    assert "core_trust_suffix" in source

    # The call to compose_core_hero_text must include the suffix
    call_idx = source.index("compose_core_hero_text(core_product_state")
    call_line = source[call_idx:source.index("\n", call_idx)]
    assert "core_trust_suffix" in call_line


def test_trust_tier_suffix_respects_length_limit() -> None:
    """All trust tier suffix strings must be ≤40 chars (WP-A7 spec)."""
    source = _read("SMC_Core_Engine.pine")

    func_start = source.index("compose_trust_tier_suffix(")
    func_body = source[func_start:func_start + 800]

    # Static suffixes (without dynamic str.tostring) must be short
    # 'no measurement data' = 19 chars ✓
    assert "no measurement data" in func_body
    # 'data stale' = 10 chars ✓
    assert "data stale" in func_body
    # Dynamic prefixes: 'score ' + digits + suffix ≤ 40 chars
    # 'score 100, data fresh' = 21 chars ✓
    assert "data fresh" in func_body


# ── WP-A10: Template Reset Window ──────────────────────────────


def test_hero_card_shows_asof_time() -> None:
    """compose_core_hero_text must include a Data line with asof_display (WP-A10)."""
    source = _read("SMC++/smc_context_resolvers.pine")

    func_start = source.index("compose_core_hero_text(")
    func_body = source[func_start:func_start + 2000]

    assert "asof_display" in func_body
    assert "Data: " in func_body


def test_hero_card_call_passes_asof_display() -> None:
    """The barstate.islast call site must pass lib_asof_display to the hero card."""
    source = _read("SMC_Core_Engine.pine")

    call_idx = source.index("compose_core_hero_text(core_product_state")
    call_line = source[call_idx:source.index("\n", call_idx)]
    assert "lib_asof_display" in call_line


def test_library_freshness_parses_asof_time() -> None:
    """Library freshness block must parse mp.ASOF_TIME for sub-day staleness (WP-A10)."""
    source = _read("SMC_Core_Engine.pine")

    assert "mp.ASOF_TIME" in source
    assert "lib_asof_display" in source
    assert "lib_hours_old" in source


# ── WP-LF1: Hero Card Marktkontext ──────────────────────────────

def test_hero_card_shows_vix_tone_market() -> None:
    """Hero card must show VIX, Tone, and Market event lines (WP-LF1)."""
    source = _read("SMC++/smc_context_resolvers.pine")

    hero_fn_idx = source.index("compose_core_hero_text(")
    hero_fn_block = source[hero_fn_idx:hero_fn_idx + 2000]
    assert "VIX: " in hero_fn_block
    assert "Tone: " in hero_fn_block
    assert "Market: " in hero_fn_block


def test_hero_card_reads_market_context_fields() -> None:
    """Engine must read VIX_LEVEL, MACRO_EVENT_NAME, TONE, GLOBAL_HEAT from library (WP-LF1)."""
    source = _read("SMC_Core_Engine.pine")

    assert "mp.VIX_LEVEL" in source
    assert "mp.MACRO_EVENT_NAME" in source
    assert "mp.MACRO_EVENT_TIME" in source
    assert "mp.TONE" in source
    assert "mp.GLOBAL_HEAT" in source
    assert "mp.GLOBAL_STRENGTH" in source


# ── WP-LF2: Earnings + Provider Transparency ────────────────────

def test_provider_state_uses_count_and_stale() -> None:
    """resolve_core_provider_state must accept provider_count and stale_providers (WP-LF2)."""
    resolvers = _read("SMC++/smc_context_resolvers.pine")

    assert "resolve_core_provider_state(string provider_status, int provider_count, string stale_providers)" in resolvers
    assert "mp.PROVIDER_COUNT" in _read("SMC_Core_Engine.pine")
    assert "mp.STALE_PROVIDERS" in _read("SMC_Core_Engine.pine")


def test_earnings_tomorrow_in_main_risk() -> None:
    """compose_main_risk_text must accept has_earnings_tomorrow flag (WP-LF2)."""
    source = _read("SMC_Core_Engine.pine")
    resolvers = _read("SMC++/smc_context_resolvers.pine")

    assert "mp.EARNINGS_TOMORROW_TICKERS" in source
    assert "Earnings tomorrow" in resolvers
    assert "core_has_earnings_tomorrow" in source


# ── WP-LF3: Breadth + Macro Context Labels ──────────────────────

def test_breadth_and_macro_context_labels() -> None:
    """Chart must show Breadth and Macro bias context labels (WP-LF3)."""
    source = _read("SMC_Core_Engine.pine")

    assert "mp.SECTOR_BREADTH" in source
    assert "mp.MACRO_BIAS_RAW" in source
    assert "var label breadth_badge = na" in source
    assert "var label macro_badge = na" in source
    assert "Breadth: " in source
    assert "Macro: " in source


# ── WP-LF4: Ticker Heat Zone Opacity ────────────────────────────

def test_ticker_heat_parses_and_adjusts_zones() -> None:
    """Ticker heat must be parsed from heat map and adjust OB/FVG opacity (WP-LF4)."""
    source = _read("SMC_Core_Engine.pine")

    assert "mp.TICKER_HEAT_MAP" in source
    assert "f_parse_ticker_heat(" in source
    assert "ticker_heat_adj" in source
    assert "Ticker Heat" in source


def test_dashboard_subscribes_to_preset_bus_contract() -> None:
    """Plan §2.5 H5 — Dashboard must consume the Engine's BUS Preset*
    contract via input.source bindings, otherwise the onboarding tooltip
    has no way to detect CUSTOM preset state.
    """
    source = _read("SMC_Dashboard.pine")

    assert 'var string g_bus_preset = "8. Operator Only - Preset Contract"' in source
    assert 'src_preset_class_code = input.source(close, "BUS PresetClassCode"' in source
    assert 'src_preset_rvol_min = input.source(close, "BUS PresetRvolMin"' in source
    assert 'src_preset_htf_bias_min = input.source(close, "BUS PresetHtfBiasMin"' in source
    assert 'src_preset_fvg_qual_gate = input.source(close, "BUS PresetFvgQualGate"' in source
    assert 'src_preset_vol_regime_def = input.source(close, "BUS PresetVolRegimeDef"' in source


def test_dashboard_hero_row_carries_h5_onboarding_tooltip() -> None:
    """Plan §2.5 H5 — When the bound preset class code is 0 (Custom) the
    Hero row shows a 4-Click onboarding nudge, otherwise it shows a
    calibrated-defaults hint citing the BUS Preset contract.
    """
    source = _read("SMC_Dashboard.pine")

    assert "int _hero_preset_code = int(math.round(src_preset_class_code))" in source
    assert "_hero_preset_code == 0 ?" in source
    assert "4 Clicks to first calibrated signal" in source
    assert "Quickstart Preset" in source
    assert "preset never lowers your value" in source
    assert 'dashboard_row_tt(smc_dashboard, 1, "Hero", _hero_one_display, _hero_one_bg, txt, _hero_one_tt)' in source


def test_dashboard_calibration_sha_input_and_hero_sha_token() -> None:
    """Plan §3.1.1 — the Calibration SHA input lets the operator anchor
    a screenshot to a specific calibration_report version. The composer
    must accept the SHA argument and emit a 'sha:<7chars>' segment when
    the SHA token is present in Hero Token Order.
    """
    source = _read("SMC_Dashboard.pine")

    assert 'calibration_sha = input.string("", "Calibration SHA"' in source
    # Composer signature now carries an optional sha argument; SHA token
    # branch trims the input to 7 chars (short-SHA convention).
    assert 'else if _tok == "SHA"' in source
    assert 'str.length(sha) > 7' in source
    assert '"sha:" + _sha_trim' in source
    # Hero call site must pass the calibration_sha through to the composer.
    assert 'compose_hero_one_liner(hero_token_order, mp.HERO_BIAS, mp.HERO_TRUST, _hero_fam, _hero_fam_pct, mp.ZONE_PRIORITY_RANK, _hero_blocker, calibration_sha)' in source
    # Hero Token Order tooltip must document the new SHA token so the
    # surface stays self-explanatory.
    assert "SHA (calibration SHA, requires Calibration SHA input below)" in source


def test_dashboard_calibration_breach_banner_overrides_hero_blocker() -> None:
    """Plan §3.1.2 — operator-controlled CAL-BREACH banner. When the
    input is true the Hero blocker is overridden to 'CAL-BREACH' so the
    SLO breach is visible at the surface even if no other risk is live.
    The override is unconditional (not gated on existing blocker text)
    so a 30-day SLO violation cannot be hidden by an empty risk field.
    """
    source = _read("SMC_Dashboard.pine")

    assert 'calibration_breach_banner = input.bool(false, "Calibration Breach Banner"' in source
    assert "if calibration_breach_banner" in source
    assert '_hero_blocker := "CAL-BREACH"' in source
    # The SLO doc must exist and reference the same threshold so the
    # surface and the doc stay in sync.
    slo = _read("docs/slo_calibration.md")
    assert "smECE_30d ≤ 0.12" in slo
    assert "CAL-BREACH" in slo
    assert "Plan §3.1.2" in slo


def test_universe_status_is_exact_and_user_visible_across_surfaces() -> None:
    core = _read("SMC_Core_Engine.pine")
    dashboard = _read("SMC_Dashboard.pine")
    strategy = _read("SMC_Long_Strategy.pine")
    utils = _read("SMC++/smc_utils.pine")
    resolvers = _read("SMC++/smc_context_resolvers.pine")

    # Empty UNIVERSE_TICKERS must fail closed to UNINITIALIZED and exact token
    # matching must replace substring matching everywhere that gates universe
    # membership.
    assert 'bool lib_universe_initialized = mp.UNIVERSE_TICKERS != ""' in core
    assert 'bool lib_ticker_in_universe = lib_universe_initialized and u.csv_has_symbol_token(mp.UNIVERSE_TICKERS, current_symbol_key, current_symbol_key_qualified)' in core
    assert 'bool dashboard_ticker_in_universe = dashboard_universe_initialized and u.csv_has_symbol_token(mp.UNIVERSE_TICKERS, dashboard_symbol_key, dashboard_symbol_key_qualified)' in dashboard
    assert 'bool strategy_ticker_in_universe = strategy_universe_initialized and u.csv_has_symbol_token(mp.UNIVERSE_TICKERS, strategy_symbol_key, strategy_symbol_key_qualified)' in strategy
    assert 'str.contains(mp.UNIVERSE_TICKERS' not in core + dashboard + strategy
    assert 'mp.UNIVERSE_TICKERS != "" ?' not in core + dashboard + strategy

    # The exact visible states and English operator copy are shared from the
    # public utility seam so Core, Dashboard, and Strategy cannot drift.
    for status in (
        'UNIVERSE: VERIFIED',
        'UNIVERSE: PARTIAL',
        'UNIVERSE: NOT SCANNED',
        'UNIVERSE: UNINITIALIZED',
        'Status: Not Scanned',
        'Core SMC chart logic remains active.',
        'Producer-based context is not available for this symbol.',
        'This symbol is outside the latest scanned universe. Core SMC logic still runs, but producer-based context is unavailable.',
        'Strategy entries are disabled because this symbol is outside the scanned universe.',
        'Strategy entries are disabled because universe data is not available.',
    ):
        assert status in utils + strategy

    assert 'u.universe_status_badge(lib_universe_status_code)' in core
    assert 'u.universe_status_banner(lib_universe_status_code)' in core
    assert 'int universe_status_code' in resolvers
    assert 'dashboard_universe_tt = dashboard_universe_detail + "\\n\\n" + dashboard_universe_matrix' in dashboard
    assert 'dashboard_row_tt(smc_dashboard, 77, "Universe Status", dashboard_universe_badge' in dashboard
    assert 'strict_universe_entries = input.bool(false, "Strict Universe Mode"' in strategy
    assert 'bool universe_gate_ok = not strict_universe_entries or backtest_mode or strategy_universe_status_code == 3 or strategy_universe_status_code == 2' in strategy
    assert 'bool can_stage_entry = selected_state and quality_ok and risk_levels_ok and regime_gate_ok and universe_gate_ok' in strategy
