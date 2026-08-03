/**
 * Find TypeScript assertions that can pass without observing anything.
 *
 * Same rule as scripts/detect_vacuous_claims.py, one language over. Three
 * shapes report success over an empty collection:
 *
 * * `for (const x of xs)` with an assert inside — zero iterations, zero
 *   assertions;
 * * `assert(xs.every(f))` / `assert.equal(xs.every(f), true)` — `[].every`
 *   is `true`;
 * * `assert(!xs.some(f))` / `assert.equal(xs.some(f), false)` — `[].some`
 *   is `false`. This is the Python analyzer's `assert not any(...)`.
 *
 * A bare `assert(xs.some(f))` is deliberately out of scope: over an empty
 * `xs` it is `false`, so it fails loudly instead of silently.
 *
 * Witnesses bind to the expression, not to the test: `assert.ok(a.length)`
 * says nothing about `b`. They also bind to the enclosing block, so a
 * witness in one `test(...)` callback does not clear an identically named
 * collection in the next one.
 *
 * Two JavaScript-specific rules, both measured against this repo rather
 * than ported on faith:
 *
 * * `assert.ok(xs)` is *not* a witness. The Python analyzer accepts a bare
 *   `assert xs` because an empty list is falsy; an empty JavaScript array
 *   is truthy, so that assertion proves nothing about emptiness.
 * * only a length comparison that actually implies "at least one" counts.
 *   `assert.equal(wrappers.length, 0, ...)` occurs in this very test suite
 *   — automation/tradingview/tests/tv_shared.test.ts:1162 ("page-chrome-only
 *   ancestors must not be treated as legend rows") and :1187 ("invisible
 *   legend buttons must be ignored") — and reading every `.length` mention
 *   as a witness would let a proven-*empty* collection exonerate a loop
 *   over it.
 */

import fs from "node:fs";
import path from "node:path";

import ts from "typescript";

export interface TsVacuousClaim {
  path: string;
  line: number;
  scope: string;
  iterable: string;
  kind: string;
  key: string;
}

/** Calls that discover things at runtime. Each can legitimately find nothing. */
const DISCOVERY_METHODS = new Set(["readdirSync", "globSync", "matchAll"]);

/**
 * Array methods that hand back a possibly shorter array.
 *
 * `.match` is deliberately absent: `String.prototype.match` returns `null`
 * or a non-empty array, so a `for … of` over it throws rather than passing
 * vacuously — and the 141 `.match(` occurrences in this test suite are
 * `assert.match`, an assertion rather than a collection producer.
 */
const EMPTIABLE_METHODS = new Set(["filter", "flatMap", "slice"]);

/** Assertions whose first two arguments are compared, not evaluated. */
const EQUALITY_ASSERTS = new Set(["equal", "strictEqual", "deepEqual", "deepStrictEqual"]);

/**
 * Render *node* as the reviewer reads it: the source text, on one line.
 *
 * This is the module's single rendering entry point. Everything that is
 * *compared* or used as an *identity* — {@link TsVacuousClaim.iterable},
 * {@link TsVacuousClaim.key}, and every witness expression checked against
 * an iterable — must go through this function and no other. The Python half
 * had to be corrected once for exactly this: witnesses rendered by a second
 * function silently failed to match the iterables they were compared
 * against, so every witness was a no-op and nothing said so.
 */
const render = (node: ts.Node, source: ts.SourceFile): string =>
  node.getText(source).replace(/\s+/g, " ").trim();

const isAssertCall = (node: ts.Node, source: ts.SourceFile): node is ts.CallExpression =>
  ts.isCallExpression(node) && /^assert/.test(render(node.expression, source));

/** The method name of `x.foo(...)`, or `null` for any other callee shape. */
const calledMethod = (node: ts.CallExpression): string | null =>
  ts.isPropertyAccessExpression(node.expression) ? node.expression.name.text : null;

/** The receiver of `x.foo(...)`; only valid once `calledMethod` matched. */
const receiverOf = (node: ts.CallExpression): ts.Expression =>
  (node.expression as ts.PropertyAccessExpression).expression;

/**
 * The nearest block-like ancestor, which is what `const` scoping follows.
 *
 * Used for both bindings and witnesses so that resolution walks the real
 * scope chain instead of the whole file.
 */
const isContainer = (node: ts.Node): boolean =>
  ts.isBlock(node) ||
  ts.isSourceFile(node) ||
  ts.isModuleBlock(node) ||
  ts.isCaseClause(node) ||
  ts.isDefaultClause(node);

const containerOf = (node: ts.Node): ts.Node | undefined => {
  let current: ts.Node | undefined = node.parent;
  while (current && !isContainer(current)) current = current.parent;
  return current;
};

/** Walk *node* and its ancestors, innermost first. */
function* selfAndAncestors(node: ts.Node): Generator<ts.Node> {
  let current: ts.Node | undefined = node;
  while (current) {
    yield current;
    current = current.parent;
  }
}

/** Per-container facts, resolved by walking a use site's scope chain. */
class ScopeChain<T> {
  private readonly byContainer = new Map<ts.Node, Map<string, T>>();

  add(container: ts.Node | undefined, name: string, value: T): void {
    if (!container) return;
    let scope = this.byContainer.get(container);
    if (!scope) {
      scope = new Map<string, T>();
      this.byContainer.set(container, scope);
    }
    scope.set(name, value);
  }

  /** The innermost value for *name* visible from *at*, or `undefined`. */
  resolve(name: string, at: ts.Node): T | undefined {
    for (const ancestor of selfAndAncestors(at)) {
      const hit = this.byContainer.get(ancestor)?.get(name);
      if (hit !== undefined) return hit;
    }
    return undefined;
  }
}

/**
 * A kind string when *node* can be empty at runtime, else `null`.
 *
 * `[]` is emptiable and `["--a", "--b"]` is not, which is why literals are
 * split rather than skipped wholesale: the recording-array idiom this test
 * suite is built on — `const calls: string[] = []`, a fake page pushes into
 * it, then the test asserts over `calls` — starts empty and stays empty
 * whenever the code under test does nothing at all.
 */
const classify = (
  node: ts.Expression,
  source: ts.SourceFile,
  bindings: ScopeChain<string>,
  at: ts.Node,
): string | null => {
  if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression)) {
    const method = node.expression.name.text;
    if (DISCOVERY_METHODS.has(method)) return "discovery call";
    if (EMPTIABLE_METHODS.has(method)) return `${method} call`;
  }
  if (ts.isArrayLiteralExpression(node)) {
    if (node.elements.length === 0) return "empty array literal";
    // `[...xs]` is the idiomatic way to materialise an iterator and passes
    // emptiness straight through — the analogue of the Python side's
    // sorted()/list() transparency.
    const spreads = node.elements.filter(ts.isSpreadElement);
    if (spreads.length === node.elements.length) {
      for (const spread of spreads) {
        const kind = classify(spread.expression, source, bindings, at);
        if (kind !== null) return kind;
      }
    }
    return null;
  }
  if (ts.isIdentifier(node)) return bindings.resolve(node.text, at) ?? null;
  // Only a dotted name that `collectBindings` actually saw being initialised
  // with something emptiable resolves here. Classifying every property
  // access would report on config literals whose contents the analyzer has
  // never seen — `CONFIG.targets` is not evidence of anything.
  if (ts.isPropertyAccessExpression(node)) {
    return bindings.resolve(render(node, source), at) ?? null;
  }
  return null;
};

/**
 * Collect `const xs = <emptiable>` bindings, keyed by their own block.
 *
 * An object literal initialiser also binds its properties by dotted name:
 * `const recording: Recording = { locatorCalls: [], filterCalls: [] }` is
 * the same recording idiom as a bare `const calls = []`, one indirection
 * further, and `tv_selectors_strict_mode.test.ts` loops over
 * `recording.filterCalls` with nothing proving it non-empty. Only these
 * bindings make a property access classifiable — see :func:`classify`.
 */
const collectBindings = (source: ts.SourceFile): ScopeChain<string> => {
  const bindings = new ScopeChain<string>();
  const visit = (node: ts.Node): void => {
    if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer) {
      const kind = classify(node.initializer, source, bindings, node);
      if (kind !== null) bindings.add(containerOf(node), node.name.text, `local ${kind}`);
      if (ts.isObjectLiteralExpression(node.initializer)) {
        for (const property of node.initializer.properties) {
          if (!ts.isPropertyAssignment(property) || !ts.isIdentifier(property.name)) continue;
          const propertyKind = classify(property.initializer, source, bindings, node);
          if (propertyKind === null) continue;
          bindings.add(
            containerOf(node),
            `${node.name.text}.${property.name.text}`,
            `local ${propertyKind}`,
          );
        }
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return bindings;
};

/** The receiver of `<expr>.length`, or `null`. */
const lengthTarget = (node: ts.Node): ts.Expression | null =>
  ts.isPropertyAccessExpression(node) && node.name.text === "length" ? node.expression : null;

const countLiteral = (node: ts.Node): number | null =>
  ts.isNumericLiteral(node) ? Number(node.text) : null;

/** True when `<length> <op> <count>` implies at least one element. */
const impliesNonEmpty = (op: ts.SyntaxKind, count: number): boolean => {
  if (op === ts.SyntaxKind.GreaterThanToken) return count >= 0;
  if (
    op === ts.SyntaxKind.GreaterThanEqualsToken ||
    op === ts.SyntaxKind.EqualsEqualsToken ||
    op === ts.SyntaxKind.EqualsEqualsEqualsToken
  ) {
    return count >= 1;
  }
  return false;
};

/**
 * Rendered expressions that *node* proves non-empty.
 *
 * Descends through `&&` and parentheses only. Under `!` or `||` a length
 * check no longer implies the collection is non-empty, and a fabricated
 * witness is the worse failure direction for this tool: it would let a
 * genuinely vacuous claim look proven.
 */
const witnessesIn = (node: ts.Expression, source: ts.SourceFile): string[] => {
  if (ts.isParenthesizedExpression(node)) return witnessesIn(node.expression, source);
  if (ts.isBinaryExpression(node)) {
    if (node.operatorToken.kind === ts.SyntaxKind.AmpersandAmpersandToken) {
      return [...witnessesIn(node.left, source), ...witnessesIn(node.right, source)];
    }
    const target = lengthTarget(node.left);
    const count = countLiteral(node.right);
    if (target && count !== null && impliesNonEmpty(node.operatorToken.kind, count)) {
      return [render(target, source)];
    }
    return [];
  }
  // `assert.ok(xs.length)` — a truthy length means at least one element.
  const direct = lengthTarget(node);
  return direct ? [render(direct, source)] : [];
};

/** Expressions proven non-empty, keyed by the block the assertion sits in. */
const collectWitnesses = (source: ts.SourceFile): ScopeChain<true> => {
  const witnesses = new ScopeChain<true>();
  const visit = (node: ts.Node): void => {
    if (isAssertCall(node, source) && node.arguments.length > 0) {
      const method = calledMethod(node);
      const first = node.arguments[0];
      // `assert.equal(xs.length, 3)` proves non-empty; `…, 0)` proves the
      // exact opposite and must never become a witness.
      const pairTarget =
        method !== null && EQUALITY_ASSERTS.has(method) && node.arguments.length >= 2
          ? lengthTarget(first)
          : null;
      const found =
        pairTarget !== null
          ? (countLiteral(node.arguments[1]) ?? 0) >= 1
            ? [render(pairTarget, source)]
            : []
          : witnessesIn(first, source);
      for (const key of found) witnesses.add(containerOf(node), key, true);
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return witnesses;
};

/** True for `throw …;` and for an exact `assert…fail(...)` call statement. */
const raisesOrFails = (node: ts.Statement, source: ts.SourceFile): boolean => {
  if (ts.isThrowStatement(node)) return true;
  return (
    ts.isExpressionStatement(node) &&
    ts.isCallExpression(node.expression) &&
    calledMethod(node.expression) === "fail" &&
    isAssertCall(node.expression, source)
  );
};

/**
 * True when falling out of *loop* throws instead of continuing.
 *
 * "Finding nothing is a failure" is the correct anti-vacuity idiom and must
 * be recognised, not flagged. The loop's next sibling is looked up in
 * whatever statement list holds it — a block, but equally a source file or
 * a `case` clause. The first draft required `ts.isBlock(loop.parent)`,
 * which made the top-level form report a claim despite the `throw` written
 * directly after it.
 */
const exhaustionThrows = (loop: ts.ForOfStatement, source: ts.SourceFile): boolean => {
  const parent = loop.parent as ts.Node & { statements?: ts.NodeArray<ts.Statement> };
  const statements = parent?.statements;
  if (!statements) return false;
  const index = statements.indexOf(loop);
  const next = index >= 0 ? statements[index + 1] : undefined;
  return next !== undefined && raisesOrFails(next, source);
};

/** The name of the enclosing `test("…", …)`, or `<module>`. */
const enclosingName = (node: ts.Node, source: ts.SourceFile): string => {
  for (const current of selfAndAncestors(node)) {
    if (ts.isCallExpression(current) && render(current.expression, source) === "test") {
      const first = current.arguments[0];
      if (first && ts.isStringLiteralLike(first)) return first.text;
    }
  }
  return "<module>";
};

/**
 * Rendered expressions, any one of which proves *node* non-empty.
 *
 * The node's own text always qualifies — that is what a witness is written
 * about. `[...a, ...b]` needs one more: concatenation only grows, so a
 * witness on any single part proves the whole non-empty, and the repo pairs
 * exactly that (`assert.equal(filterCalls.length, 6)` above a loop over
 * `[...filterCalls, ...textCalls]`, selectors.test.ts).
 *
 * Deliberately narrower than "any sub-expression": for `xs.filter(f)` a
 * non-empty `xs` proves nothing, and accepting it would fabricate a
 * witness — the worse failure direction for this tool.
 */
const witnessCandidates = (node: ts.Expression, source: ts.SourceFile): string[] => {
  const own = render(node, source);
  if (!ts.isArrayLiteralExpression(node) || node.elements.length === 0) return [own];
  const spreads = node.elements.filter(ts.isSpreadElement);
  if (spreads.length !== node.elements.length) return [own];
  return [own, ...spreads.map((spread) => render(spread.expression, source))];
};

/** The receiver of `xs.every(f)`, which is `true` over an empty `xs`. */
const everyOver = (node: ts.Expression): ts.Expression | null =>
  ts.isCallExpression(node) && calledMethod(node) === "every" ? receiverOf(node) : null;

/** The receiver of `xs.some(f)`, which is `false` over an empty `xs`. */
const someOver = (node: ts.Expression): ts.Expression | null =>
  ts.isCallExpression(node) && calledMethod(node) === "some" ? receiverOf(node) : null;

/**
 * The collection an assertion silently reports success over, or `null`.
 *
 * For an equality assertion the expected value decides the polarity, so the
 * two loud forms — `assert.equal(xs.some(f), true)` and
 * `assert.equal(xs.every(f), false)` — stay out: both *fail* over an empty
 * `xs` rather than passing.
 */
const vacuousReceiver = (call: ts.CallExpression): ts.Expression | null => {
  const first = call.arguments[0];
  if (first === undefined) return null;
  const method = calledMethod(call);
  const expected = call.arguments[1];
  if (method !== null && EQUALITY_ASSERTS.has(method) && expected !== undefined) {
    if (expected.kind === ts.SyntaxKind.TrueKeyword) return everyOver(first);
    if (expected.kind === ts.SyntaxKind.FalseKeyword) return someOver(first);
    return null;
  }
  if (ts.isPrefixUnaryExpression(first) && first.operator === ts.SyntaxKind.ExclamationToken) {
    return someOver(first.operand);
  }
  return everyOver(first);
};

export const scanSource = (sourceText: string, filePath: string): TsVacuousClaim[] => {
  const source = ts.createSourceFile(filePath, sourceText, ts.ScriptTarget.Latest, true);
  const bindings = collectBindings(source);
  const witnesses = collectWitnesses(source);
  const claims: TsVacuousClaim[] = [];
  const seen = new Set<string>();

  const record = (expression: ts.Expression, node: ts.Node): void => {
    const iterable = render(expression, source);
    if (witnessCandidates(expression, source).some((key) => witnesses.resolve(key, node))) {
      return;
    }
    const kind = classify(expression, source, bindings, node);
    if (kind === null) return;
    const scope = enclosingName(node, source);
    const key = `${path.basename(filePath)}::${scope}::${iterable}`;
    // One key must mean one decision. Several assertions in one test over
    // the same collection are healed by the same single witness, so
    // reporting them separately would only ask for the same waiver twice.
    if (seen.has(key)) return;
    seen.add(key);
    claims.push({
      path: filePath,
      line: source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1,
      scope,
      iterable,
      kind,
      key,
    });
  };

  const hasAssert = (node: ts.Node): boolean => {
    let found = false;
    const walk = (inner: ts.Node): void => {
      if (isAssertCall(inner, source)) found = true;
      ts.forEachChild(inner, walk);
    };
    walk(node);
    return found;
  };

  const visit = (node: ts.Node): void => {
    if (
      ts.isForOfStatement(node) &&
      hasAssert(node.statement) &&
      !exhaustionThrows(node, source)
    ) {
      record(node.expression, node);
    }
    if (isAssertCall(node, source)) {
      const receiver = vacuousReceiver(node);
      if (receiver) record(receiver, node);
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return claims;
};

export const scanDir = (dir: string): { files: string[]; claims: TsVacuousClaim[] } => {
  const files = fs
    .readdirSync(dir)
    .filter((name) => name.endsWith(".test.ts"))
    .sort();
  const claims = files.flatMap((name) =>
    scanSource(fs.readFileSync(path.join(dir, name), "utf-8"), name),
  );
  return { files, claims };
};
