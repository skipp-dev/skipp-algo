import type { Locator, Page } from "playwright";

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
    ? new RegExp(normalizedWords.map((part) => escapeRegex(part.slice(0, Math.min(part.length, 4)))).join(".*"), "i")
    : loose;

  return [exact, loose, fuzzy];
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
    const [exact, loose] = scriptNamePatterns(scriptName);

    return [
      page.locator('[role="dialog"]').filter({ hasText: exact }),
      page.locator('[role="dialog"]').filter({ hasText: loose }),
      page.locator('[data-name="menu-inner"]').filter({ hasText: loose }),
      page.locator('[role="status"], [role="alert"], [aria-live="polite"], [aria-live="assertive"], [data-name*="toast" i], [class*="toast" i], [class*="notification" i]').filter({ hasText: loose }),
      page.locator('[data-name*="title" i], [class*="title" i], [data-name*="header" i], [class*="header" i]').filter({ hasText: loose }),
    ];
  },

  openScriptIdentity(page: Page, scriptName: string): Locator[] {
    const [exact] = scriptNamePatterns(scriptName);

    return [
      page.getByRole("button", { name: exact }),
      page.getByRole("tab", { name: exact }),
      page.getByTitle(exact),
      page.locator('[data-name*="title" i]').getByText(exact),
      page.locator('[data-name*="header" i]').getByText(exact),
      page.locator('[data-name*="editor" i]').getByText(exact),
      page.locator('[class*="title" i]').getByText(exact),
      page.locator('[class*="header" i]').getByText(exact),
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
      page.getByRole("button", { name: /^publish$/i }),
      page.getByText(/publish script/i),
      page.getByText(/^publish$/i),
    ];
  },

  publishTitleInput(page: Page): Locator[] {
    return [
      page.getByRole("textbox", { name: /title/i }),
      page.getByPlaceholder(/title/i),
      page.locator('input[placeholder*="title" i]'),
    ];
  },

  publishDescriptionInput(page: Page): Locator[] {
    return [
      page.getByRole("textbox", { name: /description/i }),
      page.getByPlaceholder(/description/i),
      page.locator("textarea"),
    ];
  },

  privateVisibility(page: Page): Locator[] {
    return [
      page.getByRole("radio", { name: /private/i }),
      page.getByText(/^private$/i),
      page.locator('label:has-text("Private")'),
    ];
  },

  confirmPublish(page: Page): Locator[] {
    return [
      page.getByRole("button", { name: /^publish$/i }),
      page.getByRole("button", { name: /publish private/i }),
      page.getByText(/^publish$/i),
    ];
  },

  addToChart(page: Page): Locator[] {
    return [
      page.getByRole("button", { name: /add to chart/i }),
      page.getByText(/add to chart/i),
    ];
  },

  settingsForScript(page: Page, scriptName: string): Locator[] {
    const [, loose, fuzzy] = scriptNamePatterns(scriptName);

    return [
      page.getByRole("button", { name: new RegExp(`${escapeRegex(scriptName)}.*settings`, "i") }),
      page.getByTitle(loose),
      page.getByTitle(fuzzy),
      page.locator(`[title*="${scriptName}"]`),
      page.locator(`[aria-label*="${scriptName}"]`),
    ];
  },

  scriptLegendContainers(page: Page, scriptName: string): Locator[] {
    const [, loose, fuzzy] = scriptNamePatterns(scriptName);

    return [
      page.getByText(loose).locator("xpath=ancestor::div[1]"),
      page.getByText(loose).locator("xpath=ancestor::div[2]"),
      page.getByText(loose).locator("xpath=ancestor::div[3]"),
      page.getByText(fuzzy).locator("xpath=ancestor::div[1]"),
      page.getByText(fuzzy).locator("xpath=ancestor::div[2]"),
      page.getByText(fuzzy).locator("xpath=ancestor::div[3]"),
      page.getByText(loose).locator("xpath=ancestor::section[1]"),
      page.getByText(fuzzy).locator("xpath=ancestor::section[1]"),
      page.locator('[data-name*="legend" i]').filter({ hasText: loose }),
      page.locator('[data-name*="legend" i]').filter({ hasText: fuzzy }),
      page.locator('[class*="legend" i]').filter({ hasText: loose }),
      page.locator('[class*="legend" i]').filter({ hasText: fuzzy }),
      page.locator('[data-name*="source-item" i]').filter({ hasText: loose }),
      page.locator('[data-name*="source-item" i]').filter({ hasText: fuzzy }),
      page.locator('[class*="source-item" i]').filter({ hasText: loose }),
      page.locator('[class*="source-item" i]').filter({ hasText: fuzzy }),
      page.locator('[data-name*="study" i]').filter({ hasText: loose }),
      page.locator('[data-name*="study" i]').filter({ hasText: fuzzy }),
      page.locator('[class*="study" i]').filter({ hasText: loose }),
      page.locator('[class*="study" i]').filter({ hasText: fuzzy }),
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