import type { Locator, Page } from "playwright";

export type PineDraftKind = "indicator" | "strategy" | "library";

function escapeRegex(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function scriptNamePatterns(scriptName: string): RegExp[] {
  const normalizedWords = scriptName
    .split(/\s+/)
    .map((part) => part.trim())
    .filter(Boolean);
  const exact = new RegExp(
    `^${escapeRegex(scriptName)}(?:\\s+(?:v\\d+(?:\\.\\d+){1,3}|version\\s+\\d+(?:\\.\\d+){1,3}))?$`,
    "i",
  );
  const loose = new RegExp(escapeRegex(scriptName), "i");
  const fuzzy = normalizedWords.length > 0
    ? new RegExp(
      normalizedWords
        .map((part) => {
          const fullWord = escapeRegex(part);
          const truncatedWord = escapeRegex(part.slice(0, Math.min(part.length, 4)));
          return `(^|[^a-z0-9])(?:${fullWord}|${truncatedWord})(?=$|[^a-z0-9])`;
        })
        .join(".*"),
      "i",
    )
    : loose;

  return [exact, loose, fuzzy];
}

function publishedVersionContextPattern(scriptName: string): RegExp {
  return new RegExp(
    `(^|[^a-z0-9])${escapeRegex(scriptName)}(?:\\s*[:,-]?\\s*)version\\s+\\d+\\b`,
    "i",
  );
}

function publishSurface(page: Page): Locator {
  const publishFingerprint = /publish script|publish private library|publish new script|update existing script|final touches|privacy settings|tags & signature|script is not on the chart|nothing to update/i;

  // The publish dialog contains many nested `[data-id]` nodes. Treating those
  // as peer surfaces and taking `.last()` scoped the controls to an inner
  // editor node in run 31299194493, even though "Update existing script" was
  // visibly rendered in the enclosing dialog. Resolve only dialog-shaped,
  // visible containers and take the first DOM match so the outermost active
  // publish surface owns every wizard step.
  return page
    .locator([
      '#overlap-manager-root [role="dialog"]:visible',
      '#overlap-manager-root [aria-modal="true"]:visible',
      '#overlap-manager-root [data-name*="dialog" i]:visible',
      '#overlap-manager-root [class*="dialog" i]:visible',
      '#overlap-manager-root [class*="modal" i]:visible',
    ].join(", "))
    .filter({ hasText: publishFingerprint })
    .first();
}

export type ScriptRowLocatorSpec = {
  scope: "dialog" | "menu_inner";
  matchKind: "exact" | "loose";
};

export function describeScriptRowLocatorSpecs(): ScriptRowLocatorSpec[] {
  return [
    { scope: "dialog", matchKind: "exact" },
    { scope: "menu_inner", matchKind: "exact" },
    { scope: "dialog", matchKind: "loose" },
    { scope: "menu_inner", matchKind: "loose" },
  ];
}

export type ScriptRowMatchKind = "exact" | "loose";

export interface ScriptRowOptions {
  /**
   * When true, scriptRow returns ONLY locators that:
   *   - are scoped to the indicators dialog or menu-inner overlay,
   *   - filter on `[data-id^="USER;"]` (private user scripts),
   *   - require an exact (case-insensitive) script-title match (with optional
   *     trailing version suffix like " v1.2" or " version 3").
   *
   * Loose / fuzzy / global-page-scope fallbacks are suppressed. This prevents
   * the 2026-04-22 substring collision class where a third-party public script
   * such as "SMC Execution Engine (Free) by @abdallacrypto v1.3" would match
   * a preflight target named "SMC Execution". Pre-2026-04-22 callers that
   * tolerated loose matching (drafts, exploratory probes) can omit the option
   * for back-compat behavior.
   */
  strict?: boolean;
}

// The publish-flow "Continue" button may carry a leading/trailing decoration
// glyph — a stepper arrow ("Continue →" / "Continue ›"), an ellipsis, or a
// gear icon — so a bare-word regex would miss it. But the decoration must be an
// actual glyph or whitespace, NOT sentence punctuation: a label like
// "Continue?" is a confirmation *question* (a distinct, possibly destructive
// dialog). The old `[^a-z0-9]*` matched that "?" and could mis-click it, so we
// restrict tolerated decoration to a positive set (whitespace, arrows,
// ellipsis, gear + emoji variation selector) instead. Exported for unit tests.
const CONTINUE_DECORATION = "[\\s\\u2026\\u2699\\ufe0f\\u2192\\u2794\\u203a\\u00bb\\u25b8\\u25b6\\u27f6\\u21d2]";
export const PUBLISH_CONTINUE_LABEL = new RegExp(
  `^${CONTINUE_DECORATION}*continue${CONTINUE_DECORATION}*$`,
  "i",
);

export const tvSelectors = {
  pineEditor(page: Page): Locator[] {
    return [
      page.getByRole("button", { name: /^pine$/i }),
      page.getByRole("tab", { name: /^pine$/i }),
      page.getByRole("button", { name: /pine editor/i }),
      page.getByText(/^pine$/i),
      page.getByText(/pine editor/i),
    ];
  },

  cookieAccept(page: Page): Locator[] {
    return [
      page.getByRole("button", { name: /accept all/i }),
      page.getByRole("button", { name: /^accept$/i }),
      page.getByRole("button", { name: /agree/i }),
      page.getByRole("button", { name: /^ok$/i }),
      page.getByText(/accept all/i),
      page.getByText(/^accept$/i),
      page.locator('button:has-text("Accept all")'),
      page.locator('button:has-text("Accept")'),
      page.locator('[id*="cookie" i] button'),
      page.locator('[class*="cookie" i] button'),
      page.locator('[id*="consent" i] button'),
      page.locator('[class*="consent" i] button'),
    ];
  },

  openScript(page: Page): Locator[] {
    return [
      page.getByRole("button", { name: /^open$/i }),
      page.getByRole("button", { name: /open script/i }),
      page.getByText(/^open$/i),
    ];
  },

  currentScriptMenu(page: Page): Locator[] {
    const pineDialog = page.locator('[data-name="pine-dialog"], #pine-editor-dialog, [id*="pine-editor" i]').last();
    const headerPattern = /untitled|smc|skipp|usi|choch|rev/i;

    return [
      pineDialog.locator('button[aria-haspopup="menu"], [role="button"][aria-haspopup="menu"]').first(),
      page.locator('[data-name="pine-dialog"] [role="button"]').first(),
      page.locator('#pine-editor-dialog [role="button"]').first(),
      pineDialog.getByRole("button", { name: headerPattern }).first(),
      pineDialog.getByText(headerPattern).last(),
    ];
  },

  createNewScript(page: Page): Locator[] {
    return [
      page.getByRole("menuitem", { name: /create new/i }),
      page.getByRole("button", { name: /create new/i }),
      page.getByText(/create new/i),
    ];
  },

  createNewScriptKind(page: Page, kind: PineDraftKind): Locator[] {
    const pattern = new RegExp(`^${escapeRegex(kind)}$`, "i");

    return [
      page.getByRole("menuitem", { name: pattern }),
      page.getByRole("button", { name: pattern }),
      page.getByText(pattern),
    ];
  },

  openScriptAction(page: Page): Locator[] {
    return [
      page.getByRole("menuitem", { name: /open script/i }),
      page.getByRole("button", { name: /open script/i }),
      page.getByText(/open script/i),
    ];
  },

  myScriptsTab(page: Page): Locator[] {
    return [
      page.getByRole("tab", { name: /my scripts/i }),
      page.getByText(/my scripts/i),
      page.getByText(/personal/i),
    ];
  },

  scriptSearch(page: Page): Locator[] {
    return [
      page.getByRole("textbox", { name: /search/i }),
      page.getByPlaceholder(/search/i),
      page.locator('input[type="search"]'),
      page.locator('input[placeholder*="Search" i]'),
    ];
  },

  scriptRow(page: Page, scriptName: string, opts: ScriptRowOptions = {}): Locator[] {
    const [exact, loose] = scriptNamePatterns(scriptName);
    const dialog = page.locator('[role="dialog"]');
    const indicatorsDialog = page.locator('[data-name="indicators-dialog"]');
    const menuInner = page.locator('[data-name="menu-inner"]');

    if (opts.strict) {
      // Strict mode: USER-scoped, exact pattern only. No loose, no fuzzy, no
      // global-page scope. See ScriptRowOptions docstring for rationale.
      return [
        indicatorsDialog.locator('[data-id^="USER;"]').filter({ hasText: exact }),
        menuInner.locator('[data-id^="USER;"]').filter({ hasText: exact }),
        dialog.locator('[data-id^="USER;"]').filter({ hasText: exact }),
      ];
    }

    const patterns = { exact, loose } as const;
    const scopes = {
      dialog,
      menu_inner: menuInner,
    } as const;

    return [
      indicatorsDialog.locator('[data-id^="USER;"]').filter({ hasText: exact }),
      indicatorsDialog.locator('[data-id^="USER;"]').filter({ hasText: loose }),
      ...describeScriptRowLocatorSpecs().map((spec) => scopes[spec.scope].getByText(patterns[spec.matchKind])),
      indicatorsDialog.getByText(exact),
      indicatorsDialog.locator('[data-id], [class*="container" i], [class*="main" i], [class*="title" i]').filter({ hasText: exact }),
      indicatorsDialog.getByText(loose),
      indicatorsDialog.locator('[data-id], [class*="container" i], [class*="main" i], [class*="title" i]').filter({ hasText: loose }),
    ];
  },

  openScriptRow(page: Page, scriptName: string): Locator[] {
    const [exact] = scriptNamePatterns(scriptName);
    const indicatorsDialog = page.locator('[data-name="indicators-dialog"]');
    const dialog = page.locator('[role="dialog"]');
    const menuInner = page.locator('[data-name="menu-inner"]');
    const openDialogRows = '[data-id], [role="option"], [role="menuitem"], [class*="item" i], [class*="row" i], [class*="title" i]';

    return [
      indicatorsDialog.locator('[data-id^="USER;"]').filter({ hasText: exact }),
      menuInner.locator('[data-id^="USER;"]').filter({ hasText: exact }),
      dialog.locator('[data-id^="USER;"]').filter({ hasText: exact }),
      indicatorsDialog.locator(openDialogRows).filter({ hasText: exact }),
      menuInner.locator(openDialogRows).filter({ hasText: exact }),
      dialog.locator(openDialogRows).filter({ hasText: exact }),
      indicatorsDialog.getByText(exact),
      menuInner.getByText(exact),
      dialog.getByText(exact),
    ];
  },

  openScriptExactTitle(page: Page, scriptName: string): Locator[] {
    const [exact] = scriptNamePatterns(scriptName);
    const indicatorsDialog = page.locator('[data-name="indicators-dialog"]');
    const menuInner = page.locator('[data-name="menu-inner"]');
    const dialog = page.locator('[role="dialog"]');

    // Deliberately target the exact title text rather than an ancestor row.
    // TradingView can accept a click on a broad matching container, repaint
    // the editor title, and still leave the previous Monaco buffer visible.
    return [
      indicatorsDialog.getByText(exact),
      menuInner.getByText(exact),
      dialog.getByText(exact),
    ];
  },

  publishedVersionContext(page: Page, scriptName: string): Locator[] {
    const exactVersionContext = publishedVersionContextPattern(scriptName);

    return [
      page.locator('[role="dialog"]').filter({ hasText: exactVersionContext }),
      page.locator('[data-name="menu-inner"]').filter({ hasText: exactVersionContext }),
      page.locator('[role="status"], [role="alert"], [aria-live="polite"], [aria-live="assertive"], [data-name*="toast" i], [class*="toast" i], [class*="notification" i]').filter({ hasText: exactVersionContext }),
      page.locator('[data-name*="title" i], [class*="title" i], [data-name*="header" i], [class*="header" i]').filter({ hasText: exactVersionContext }),
    ];
  },

  openScriptIdentity(page: Page, scriptName: string): Locator[] {
    const [exact, , fuzzy] = scriptNamePatterns(scriptName);
    const titleScopes = [
      page.locator('[data-name*="title" i]'),
      page.locator('[data-name*="header" i]'),
      page.locator('[class*="title" i]'),
      page.locator('[class*="header" i]'),
    ];

    return [
      page.getByRole("button", { name: exact }),
      page.getByRole("tab", { name: exact }),
      page.getByRole("heading", { name: exact }),
      page.getByTitle(exact),
      ...titleScopes.flatMap((locator) => [
        locator.filter({ hasText: exact }),
        locator.filter({ hasText: fuzzy }),
      ]),
    ];
  },

  editorHosts(page: Page): Locator[] {
    return [
      page.locator(".monaco-editor"),
      page.locator('[class*="monaco-editor"]'),
      page.locator('[data-name*="editor"]'),
      page.locator("textarea"),
      page.locator('[contenteditable="true"]'),
    ];
  },

  editorFallback(page: Page): Locator[] {
    return this.editorHosts(page);
  },

  saveNameInput(page: Page): Locator[] {
    return [
      page.getByRole("textbox", { name: /name/i }),
      page.getByRole("textbox", { name: /title/i }),
      page.getByPlaceholder(/script name/i),
      page.getByPlaceholder(/name/i),
      page.locator('input[placeholder*="name" i]'),
    ];
  },

  saveButtons(page: Page): Locator[] {
    return [
      page.getByRole("button", { name: /^save$/i }),
      page.getByRole("button", { name: /save script/i }),
      page.getByText(/^save$/i),
    ];
  },

  publishButtons(page: Page): Locator[] {
    // The header-level "publish-chart-button" publishes chart layouts/ideas,
    // not Pine scripts. Exclude it and all descendants from generic "Publish"
    // fallbacks to avoid opening the wrong flow.
    const notChart = ':not(.publish-chart-button):not(.publish-chart-button *)';
    const notShare = ':not([aria-label*="share" i]):not([data-tooltip*="share" i])';

    return [
      page.getByRole("button", { name: /publish script/i }),
      page.getByRole("button", { name: /publish library/i }),
      page.getByRole("button", { name: /^publish$/i }).and(page.locator(notChart)),
      page.locator(`button${notShare}${notChart}`).filter({ hasText: /^publish$/i }),
      page.locator(`[role="button"]${notShare}${notChart}`).filter({ hasText: /^publish$/i }),
      page.locator(`[class*="button" i]${notShare}${notChart}`).filter({ hasText: /^publish$/i }),
      page.locator(`[data-name*="button" i]${notShare}${notChart}`).filter({ hasText: /^publish$/i }),
      page.getByText(/publish script/i),
      page.getByText(/publish library/i),
      page.getByText(/^publish$/i).and(page.locator(notChart)),
    ];
  },

  pinePublishButtons(page: Page): Locator[] {
    const pineDialog = page.locator('[data-name="pine-dialog"], #pine-editor-dialog, [id*="pine-editor" i]').last();

    return [
      // TradingView relabelled this control: the Pine editor header button that
      // starts the publish flow is now titled "Share your script with
      // community" and contains the word "publish" NOWHERE. Every pattern
      // below keys on "publish", so all of them missed and openPublishSurface
      // reported "Could not open publish flow" — which is why
      // smc-library-refresh has been unable to publish since 2026-07-30 while
      // generating the library fine and passing its auth probe.
      //
      // Measured 2026-07-31 in the editor header: "Add to chart", an unnamed
      // button, [title="Share your script with community"], "More". Clicking it
      // opens the publish flow, which immediately shows the known
      // "Script is not on the chart" gate that hasPublishAddToChartGate already
      // handles.
      pineDialog.locator('[title="Share your script with community"]'),
      pineDialog.locator('[title*="share your script" i]'),
      // The title selectors above are SINGLE-USE: the control carries
      // apply-common-tooltip, which strips the title attribute on click and
      // does not restore it while the pointer rests on the button. Measured
      // 2026-07-31 publishing smc_context_engine_private v5: the first open
      // matched by title, the "Script is not on the chart" gate was cleared,
      // and the REOPEN missed all 11 candidates — same mechanism as the
      // Replay Forward button. TradingView's own class name for the control
      // (className publishButton-ddmSLPrc apply-common-tooltip ...) survives
      // the strip; the hashed suffix does not, so match the stable prefix.
      pineDialog.locator('button[class*="publishButton"]'),
      pineDialog.getByRole("button", { name: /publish script/i }),
      pineDialog.getByRole("button", { name: /publish library/i }),
      pineDialog.getByRole("button", { name: /^publish$/i }),
      pineDialog.locator('button').filter({ hasText: /^publish$/i }),
      pineDialog.locator('[role="button"]').filter({ hasText: /^publish$/i }),
      pineDialog.locator('[class*="button" i], [data-name*="button" i]').filter({ hasText: /^publish$/i }),
      pineDialog.getByText(/publish script/i),
      pineDialog.getByText(/publish library/i),
      pineDialog.getByText(/^publish$/i),
    ];
  },

  publishScriptAction(page: Page): Locator[] {
    const activeMenu = page.locator('#overlap-manager-root [role="menu"], #overlap-manager-root [data-name*="menu" i], #overlap-manager-root [class*="menu" i]').last();

    return [
      activeMenu.getByRole("menuitem", { name: /publish script/i }),
      activeMenu.getByRole("menuitem", { name: /publish library/i }),
      activeMenu.getByRole("button", { name: /publish script/i }),
      activeMenu.getByRole("button", { name: /publish library/i }),
      activeMenu.locator('[role="menuitem"], [role="button"], button').filter({ hasText: /publish script|publish library|update .*library/i }),
      page.getByRole("menuitem", { name: /publish script/i }),
      page.getByRole("menuitem", { name: /publish library/i }),
      page.getByRole("button", { name: /publish script/i }),
      page.getByRole("button", { name: /publish library/i }),
      page.getByText(/publish script/i),
      page.getByText(/publish library/i),
      page.getByText(/update .*library/i),
    ];
  },

  publishTitleInput(page: Page): Locator[] {
    const surface = publishSurface(page);

    return [
      surface.getByRole("textbox", { name: /title/i }),
      surface.getByPlaceholder(/title/i),
      surface.locator('input[placeholder*="title" i]'),
    ];
  },

  publishDescriptionInput(page: Page): Locator[] {
    const surface = publishSurface(page);

    return [
      surface.getByRole("textbox", { name: /description/i }),
      surface.getByPlaceholder(/description/i),
      surface.locator("textarea"),
      surface.locator('[contenteditable="true"][aria-label*="description" i]'),
      surface.locator('[contenteditable="true"][data-placeholder*="description" i]'),
      surface.locator('[class*="description" i] [contenteditable="true"]'),
      surface.locator('[contenteditable="true"][role="textbox"]').last(),
      surface.locator('[contenteditable="true"]').last(),
    ];
  },

  publishUpdateExistingMode(page: Page): Locator[] {
    const surface = publishSurface(page);
    const exact = /^update existing script$/i;

    return [
      surface.getByRole("tab", { name: exact }),
      surface.getByRole("button", { name: exact }),
      surface.getByRole("radio", { name: exact }),
      surface.locator('[role="tab"], [role="button"], button, label').filter({ hasText: exact }),
      surface.getByText(exact, { exact: true }),
    ];
  },

  publishValidationError(page: Page): Locator[] {
    const surface = publishSurface(page);
    const knownValidation = /script description is required|script title is required|description is required|title is required/i;

    return [
      surface.getByRole("alert").filter({ hasText: knownValidation }),
      surface.getByText(knownValidation),
      surface.locator('[class*="error" i], [data-name*="error" i]').filter({ hasText: knownValidation }),
    ];
  },

  privateVisibility(page: Page): Locator[] {
    const surface = publishSurface(page);

    return [
      surface.getByRole("radio", { name: /private/i }),
      surface.getByText(/^private$/i),
      surface.locator('label:has-text("Private")'),
    ];
  },

  confirmPublish(page: Page): Locator[] {
    const surface = publishSurface(page);

    return [
      surface.getByRole("button", { name: /publish new version/i }).last(),
      surface.getByRole("button", { name: /update .*library/i }).last(),
      surface.getByRole("button", { name: /^update$/i }).last(),
      surface.getByRole("button", { name: /publish script/i }).last(),
      surface.getByRole("button", { name: /publish private/i }).last(),
      surface.getByRole("button", { name: /publish privately/i }).last(),
      surface.getByRole("button", { name: /private script/i }).last(),
      surface.getByRole("button", { name: /publish library/i }).last(),
      surface.getByRole("button", { name: /^publish$/i }).last(),
      page.locator('#overlap-manager-root').getByRole("button", { name: /publish new version/i }).last(),
      page.locator('#overlap-manager-root').getByRole("button", { name: /update .*library/i }).last(),
      page.locator('#overlap-manager-root').getByRole("button", { name: /^update$/i }).last(),
      page.locator('#overlap-manager-root').getByRole("button", { name: /publish script/i }).last(),
      page.locator('#overlap-manager-root').getByRole("button", { name: /publish private/i }).last(),
      page.locator('#overlap-manager-root').getByRole("button", { name: /publish privately/i }).last(),
      page.locator('#overlap-manager-root').getByRole("button", { name: /private script/i }).last(),
      page.locator('#overlap-manager-root').getByRole("button", { name: /publish library/i }).last(),
      page.locator('#overlap-manager-root').getByRole("button", { name: /^publish$/i }).last(),
      page.locator('#overlap-manager-root button').filter({ hasText: /publish new version|update .*library|publish script|publish private|publish privately|private script|publish library|^publish$/i }).last(),
      page.locator('#overlap-manager-root [role="button"]').filter({ hasText: /publish new version|update .*library|publish script|publish private|publish privately|private script|publish library|^publish$/i }).last(),
    ];
  },

  publishContinue(page: Page): Locator[] {
    const surface = publishSurface(page);

    // Tolerate a leading/trailing decoration glyph ("Continue →"/"Continue ›")
    // via PUBLISH_CONTINUE_LABEL — this group has no substring/attribute
    // fallback, so an anchored bare-word regex would miss every branch. The
    // positive decoration set still rejects both "Continue editing" and the
    // "Continue?" confirmation question.
    return [
      surface.getByRole("button", { name: PUBLISH_CONTINUE_LABEL }).last(),
      surface.getByText(PUBLISH_CONTINUE_LABEL).last(),
      page.locator('#overlap-manager-root').getByRole("button", { name: PUBLISH_CONTINUE_LABEL }).last(),
      page.locator('#overlap-manager-root button').filter({ hasText: PUBLISH_CONTINUE_LABEL }).last(),
      page.locator('#overlap-manager-root [role="button"]').filter({ hasText: PUBLISH_CONTINUE_LABEL }).last(),
      page.locator('#overlap-manager-root').getByText(PUBLISH_CONTINUE_LABEL).last(),
    ];
  },

  addToChart(page: Page): Locator[] {
    return [
      page.getByRole("button", { name: /add to chart/i }),
      page.getByText(/add to chart/i),
    ];
  },

  indicators(page: Page): Locator[] {
    return [
      page.getByRole("button", { name: /^indicators$/i }),
      page.getByRole("button", { name: /indicators/i }),
      page.getByText(/^indicators$/i),
      page.getByText(/indicators/i),
    ];
  },

  settingsForScript(page: Page, scriptName: string): Locator[] {
    const [exact] = scriptNamePatterns(scriptName);

    return [
      page.getByRole("button", { name: new RegExp(`^${escapeRegex(scriptName)}\\s+settings$`, "i") }),
      page.getByRole("button", { name: new RegExp(`^settings\\s+${escapeRegex(scriptName)}$`, "i") }),
      page.getByTitle(exact),
    ];
  },

  scriptLegendContainers(page: Page, scriptName: string): Locator[] {
    const [exact] = scriptNamePatterns(scriptName);

    return [
      page.getByText(exact).locator("xpath=ancestor::div[1]"),
      page.getByText(exact).locator("xpath=ancestor::div[2]"),
      page.getByText(exact).locator("xpath=ancestor::div[3]"),
      page.getByText(exact).locator("xpath=ancestor::section[1]"),
    ];
  },

  legendMenuButtons(container: Locator): Locator[] {
    return [
      container.locator('[aria-haspopup="menu"]'),
      container.locator('button[aria-label*="more" i]'),
      container.locator('[role="button"][aria-label*="more" i]'),
      container.locator('button[title*="more" i]'),
      container.locator('[role="button"][title*="more" i]'),
      container.locator('button[aria-label*="menu" i]'),
      container.locator('[role="button"][aria-label*="menu" i]'),
      container.locator('button[aria-label*="settings" i]'),
      container.locator('[role="button"][aria-label*="settings" i]'),
      container.locator('[data-name*="menu" i]'),
      container.locator('[class*="menu" i]'),
      container.locator('button'),
      container.locator('[role="button"]'),
    ];
  },

  legendSettingsButtons(container: Locator): Locator[] {
    return [
      container.locator('button[data-qa-id="legend-settings-action"]'),
      container.locator('button[aria-label="Settings"]'),
      container.locator('button[title="Settings"]'),
      container.locator('[role="button"][aria-label="Settings"]'),
      container.locator('[role="button"][title="Settings"]'),
    ];
  },

  settingsAction(page: Page): Locator[] {
    // The text regexes tolerate a leading/trailing gear glyph, emoji, arrow or
    // "..." ("⚙ Settings") — anchoring only on the bare word would miss the
    // menuitem/role-button branches that lack an aria-label/title/has-text
    // fallback. `[^a-z0-9]` still rejects phrases like "Chart Settings".
    return [
      page.locator('[role="menu"] [role="menuitem"]').filter({ hasText: /^[^a-z0-9]*settings[^a-z0-9]*$/i }),
      page.locator('[role="menu"] [role="button"]').filter({ hasText: /^[^a-z0-9]*settings[^a-z0-9]*$/i }),
      page.locator('[role="menu"] [role="button"][aria-label="Settings"]'),
      page.locator('[role="menu"] button[title="Settings"]'),
      page.locator('[role="menu"] button[title^="Settings" i]'),
      page.locator('[role="menu"] button:has-text("Settings")'),
      page.locator('[data-name*="menu" i]').getByText(/^[^a-z0-9]*settings[^a-z0-9]*$/i),
      page.locator('[role="menu"]').getByText(/^[^a-z0-9]*settings[^a-z0-9]*$/i),
    ];
  },

  chartSurfaceSettingsButtons(page: Page): Locator[] {
    return [
      page.locator('button[aria-label="Settings"]:not([data-name="header-toolbar-properties"])'),
      page.locator('button[title="Settings"]:not([data-name="header-toolbar-properties"])'),
      page.locator('[role="button"][aria-label="Settings"]:not([data-name="header-toolbar-properties"])'),
      page.locator('[role="button"][title="Settings"]:not([data-name="header-toolbar-properties"])'),
    ];
  },

  chartSurfaceMoreButtons(page: Page): Locator[] {
    return [
      page.locator('button[aria-label="More"]'),
      page.locator('button[title="More"]'),
      page.locator('[role="button"][aria-label="More"]'),
      page.locator('[role="button"][title="More"]'),
    ];
  },

  inputsTab(page: Page): Locator[] {
    return [
      page.getByRole("tab", { name: /inputs/i }),
      page.getByText(/^inputs$/i),
    ];
  },

  closeModal(page: Page): Locator[] {
    return [
      page.getByRole("button", { name: /close/i }),
      page.locator('[aria-label="Close"]'),
      page.locator('[title="Close"]'),
    ];
  },
};
