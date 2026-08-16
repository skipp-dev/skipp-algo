import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import {
  HAND_LIBS,
  parseHandLibDeps,
  repinImport,
  resolveDeps,
  topoSort,
  type HandLib,
} from "../../../scripts/tv_publish_hand_authored_libraries.js";

const _repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..");

test("parseHandLibDeps extracts owner-scoped hand-lib deps only", () => {
  const src = [
    "library(\"smc_utils\")",
    "import preuss_steffen/smc_core_types/5 as ct",
    "import someone_else/other/1 as x",
    "import preuss_steffen/smc_micro_profiles_generated/152 as mp",
  ].join("\n");
  const known = new Set(["smc_core_types", "smc_utils"]);
  assert.deepEqual(parseHandLibDeps(src, known), ["smc_core_types"]);
});

test("repinImport rewrites any pinned version to the target", () => {
  const before = "import preuss_steffen/smc_utils/3 as u\nplot(1)\n";
  const { text, changed } = repinImport(before, "smc_utils", 4);
  assert.equal(changed, true);
  assert.ok(text.includes("preuss_steffen/smc_utils/4"));
  // A library it does not mention is untouched.
  assert.equal(repinImport(before, "smc_draw", 9).changed, false);
});

test("topoSort orders dependencies before dependents and is stable", () => {
  const libs: HandLib[] = [
    { name: "a", source: "", publisher: null },
    { name: "b", source: "", publisher: null },
    { name: "c", source: "", publisher: null },
  ];
  // c depends on b, b depends on a  ->  a, b, c
  const deps = new Map<string, string[]>([
    ["a", []],
    ["b", ["a"]],
    ["c", ["b"]],
  ]);
  assert.deepEqual(topoSort(libs, deps).map((l) => l.name), ["a", "b", "c"]);
});

test("topoSort throws on a cycle", () => {
  const libs: HandLib[] = [
    { name: "a", source: "", publisher: null },
    { name: "b", source: "", publisher: null },
  ];
  const deps = new Map<string, string[]>([
    ["a", ["b"]],
    ["b", ["a"]],
  ]);
  assert.throws(() => topoSort(libs, deps), /Cyclic/);
});

test("the REAL hand-lib graph is acyclic and puts every dep before its dependent", () => {
  const deps = resolveDeps(HAND_LIBS, _repoRoot);
  const order = topoSort(HAND_LIBS, deps);
  assert.equal(order.length, HAND_LIBS.length);
  const pos = new Map(order.map((l, i) => [l.name, i]));
  for (const lib of HAND_LIBS) {
    for (const dep of deps.get(lib.name) ?? []) {
      assert.ok(
        pos.get(dep)! < pos.get(lib.name)!,
        `${dep} must be published before ${lib.name}`,
      );
    }
  }
  // Known invariant from the sources: utils depends on core_types.
  assert.ok(pos.get("smc_core_types")! < pos.get("smc_utils")!);
  // Every hand-lib now has a publisher — the earlier smc_bus_private gap is closed.
  assert.ok(HAND_LIBS.every((l) => l.publisher !== null), "every hand-lib must have a publisher");
});

test("every hand-lib with a publisher points at an existing tv_publish_* script", () => {
  for (const lib of HAND_LIBS) {
    if (lib.publisher) {
      assert.ok(
        fs.existsSync(path.join(_repoRoot, lib.publisher)),
        `${lib.name}: publisher ${lib.publisher} must exist`,
      );
    }
    assert.ok(
      fs.existsSync(path.join(_repoRoot, lib.source)),
      `${lib.name}: source ${lib.source} must exist`,
    );
  }
});

test("the smc_bus_private publisher descriptor is not a leftover draw-template copy", () => {
  // Facade-authoritative verification is proven for every hand-authored
  // publisher, converted or not, by
  // hand_authored_publisher_facade_authority.test.ts (assertDelegatesTo-
  // SharedFacadeAuthority / assertWiresFacadeAuthority). Once
  // tv_publish_bus_library.ts became a descriptor wrapper
  // (handlib-publisher-dedup, 2026-08-14) it no longer contains that logic
  // inline — getFlag(...) calls, the VersionVerificationMode union, and the
  // facade probe now all live in the shared module, not here. This test's
  // remaining job is the one property that guard does not cover: that the
  // wrapper's descriptor actually names the bus library rather than a
  // copy-pasted draw one (#3609 pattern origin).
  const src = fs.readFileSync(path.join(_repoRoot, "scripts", "tv_publish_bus_library.ts"), "utf-8");
  assert.ok(src.includes('scriptName: "smc_bus_private"'), "descriptor must name smc_bus_private");
  assert.equal(src.includes("smc_draw"), false, "no leftover draw-template identity");
});

test("an unreadable consumer directory fails loudly instead of shrinking the scan", () => {
  // 2026-08-15 sweep: `catch { continue; }` on readdirSync swallowed ANY
  // error, not just ENOENT — a permissions or I/O failure read as "no .pine
  // consumers there", silently shrinking the population the repin scan
  // claims to cover. ENOENT (the directory legitimately may not exist)
  // stays quiet; everything else must throw.
  const here = path.dirname(fileURLToPath(import.meta.url));
  for (const rel of [
    ["..", "..", "..", "scripts", "tv_publish_hand_authored_libraries.ts"],
    ["..", "lib", "tv_publish_hand_lib.ts"],
    ["..", "..", "..", "scripts", "build_pine_library_version_snapshot.ts"],
  ]) {
    const source = fs.readFileSync(path.join(here, ...rel), "utf-8");
    const bare = source.match(/readdirSync[^\n]*\n\s*\} catch \{/g) ?? [];
    assert.deepEqual(bare, [], `${rel.join("/")}: bodyless catch on readdirSync swallows non-ENOENT errors`);
    assert.match(source, /code === "ENOENT"/, `${rel.join("/")}: the ENOENT-only guard is gone`);
  }
});
