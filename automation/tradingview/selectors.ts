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
  const exact = new RegExp(`^${escapeRegex(scriptName)}$`, "i");
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
  return page.locator('#overlap-manager-root [role="dialog"], #overlap-manager-root [data-id], #overlap-manager-root [data-name*="dialog" i], #overlap-manager-root [class*="dialog" i], #overlap-manager-root [class*="modal" i]').last();
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
    return [
      page.locator('[data-name="pine-dialog"] [role="button"]').first(),
      page.locator('#pine-editor-dialog [role="button"]').first(),
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

  scriptRow(page: Page, scriptName: string): Locator[] {
    const [exact, loose] = scriptNamePatterns(scriptName);
    const dialog = page.locator('[role="dialog"]');
    const menuInner = page.locator('[data-name="menu-inner"]');
    const patterns = { exact, loose } as const;
    const scopes = {
      dialog,
      menu_inner: menuInner,
    } as const;

    return describeScriptRowLocatorSpecs().map((spec) => scopes[spec.scope].getByText(patterns[spec.matchKind]));
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
    const pineDialogScope = page.locator('[data-name="pine-dialog"], #pine-editor-dialog, [id*="pine-editor" i]');
    const titleScopes = [
      page.locator('[data-name*="title" i]'),
      page.locator('[data-name*="header" i]'),
      page.locator('[data-name*="editor" i]'),
      page.locator('[class*="title" i]'),
      page.locator('[class*="header" i]'),
    ];

    return [
      page.getByRole("button", { name: exact }),
      page.getByRole("tab", { name: exact }),
      page.getByTitle(exact),
      page.getByTitle(fuzzy),
      pineDialogScope.getByText(exact),
      pineDialogScope.getByText(fuzzy),
      ...titleScopes.flatMap((locator) => [
        locator.getByText(exact),
        locator.getByText(fuzzy),
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
    return [
      page.getByRole("button", { name: /publish script/i }),
      page.getByRole("button", { name: /publish library/i }),
      page.getByRole("button", { name: /^publish$/i }),
      page.locator('button:not([aria-label*="share" i]):not([data-tooltip*="share" i])').filter({ hasText: /^publish$/i }),
      page.locator('[role="button"]:not([aria-label*="share" i]):not([data-tooltip*="share" i])').filter({ hasText: /^publish$/i }),
      page.locator('[class*="button" i]:not([aria-label*="share" i]):not([data-tooltip*="share" i])').filter({ hasText: /^publish$/i }),
      page.locator('[data-name*="button" i]:not([aria-label*="share" i]):not([data-tooltip*="share" i])').filter({ hasText: /^publish$/i }),
      page.getByText(/publish script/i),
      page.getByText(/publish library/i),
      page.getByText(/^publish$/i),
    ];
  },

  pinePublishButtons(page: Page): Locator[] {
    const pineDialog = page.locator('[data-name="pine-dialog"], #pine-editor-dialog, [id*="pine-editor" i]').last();

    return [
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
      surface.getByRole("button", { name: /publish private/i }).last(),
      surface.getByRole("button", { name: /publish library/i }).last(),
      surface.getByRole("button", { name: /^publish$/i }).last(),
      page.locator('#overlap-manager-root').getByRole("button", { name: /publish new version/i }).last(),
      page.locator('#overlap-manager-root').getByRole("button", { name: /update .*library/i }).last(),
      page.locator('#overlap-manager-root').getByRole("button", { name: /^update$/i }).last(),
      page.locator('#overlap-manager-root').getByRole("button", { name: /publish private/i }).last(),
      page.locator('#overlap-manager-root').getByRole("button", { name: /publish library/i }).last(),
      page.locator('#overlap-manager-root').getByRole("button", { name: /^publish$/i }).last(),
      page.locator('#overlap-manager-root button').filter({ hasText: /publish new version|update .*library|publish private|publish library|^publish$/i }).last(),
      page.locator('#overlap-manager-root [role="button"]').filter({ hasText: /publish new version|update .*library|publish private|publish library|^publish$/i }).last(),
      surface.getByText(/publish new version/i).last(),
      surface.getByText(/update .*library/i).last(),
      page.locator('#overlap-manager-root').getByText(/publish new version/i).last(),
      page.locator('#overlap-manager-root').getByText(/update .*library/i).last(),
      page.locator('#overlap-manager-root').getByText(/publish library/i).last(),
    ];
  },

  publishContinue(page: Page): Locator[] {
    const surface = publishSurface(page);

    return [
      surface.getByRole("button", { name: /^continue$/i }).last(),
      surface.getByText(/^continue$/i).last(),
      page.locator('#overlap-manager-root').getByRole("button", { name: /^continue$/i }).last(),
      page.locator('#overlap-manager-root button').filter({ hasText: /^continue$/i }).last(),
      page.locator('#overlap-manager-root [role="button"]').filter({ hasText: /^continue$/i }).last(),
      page.locator('#overlap-manager-root').getByText(/^continue$/i).last(),
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
    return [
      page.locator('[role="menu"] [role="menuitem"]').filter({ hasText: /^settings(\.\.\.)?$/i }),
      page.locator('[role="menu"] [role="button"]').filter({ hasText: /^settings(\.\.\.)?$/i }),
      page.locator('[role="menu"] [role="button"][aria-label="Settings"]'),
      page.locator('[role="menu"] button[title="Settings"]'),
      page.locator('[role="menu"] button[title^="Settings" i]'),
      page.locator('[role="menu"] button:has-text("Settings")'),
      page.locator('[data-name*="menu" i]').getByText(/^settings(\.\.\.)?$/i),
      page.locator('[role="menu"]').getByText(/^settings(\.\.\.)?$/i),
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