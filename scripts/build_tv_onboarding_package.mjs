#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(import.meta.url);

function flag(name, fallback = "") {
  const args = process.argv.slice(2);
  const index = args.indexOf(name);
  return index >= 0 && args[index + 1] ? args[index + 1] : fallback;
}

function normalizedPlatform() {
  if (process.platform === "win32") return "windows";
  if (process.platform === "darwin") return "macos";
  return process.platform;
}

function parseBindingLabels(source) {
  return [...source.matchAll(/input\.source\([^,]+,\s*(["'])(.*?)\1/g)]
    .map((match) => match[2])
    .filter((label) => label.startsWith("BUS "));
}

function copyPackage(packageName, destination) {
  const packageJson = require.resolve(`${packageName}/package.json`);
  fs.cpSync(path.dirname(packageJson), destination, { recursive: true });
}

function findNodeLicense(executable) {
  const binDir = path.dirname(fs.realpathSync(executable));
  const candidates = [
    path.join(binDir, "LICENSE"),
    path.join(binDir, "LICENSE.txt"),
    path.join(path.dirname(binDir), "LICENSE"),
    path.join(path.dirname(binDir), "LICENSE.txt"),
  ];
  return candidates.find((candidate) => fs.existsSync(candidate)) || null;
}

function filesUnder(directory) {
  const files = [];
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const full = path.join(directory, entry.name);
    if (entry.isDirectory()) files.push(...filesUnder(full));
    else if (entry.isFile()) files.push(full);
  }
  return files;
}

function sha256(file) {
  return crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex");
}

function portableConfig() {
  const configPath = path.join(root, "automation", "tradingview", "config", "consumer-onboarding.json");
  const raw = JSON.parse(fs.readFileSync(configPath, "utf-8"));
  return {
    ...raw,
    consumers: raw.consumers.map((consumer) => {
      const bindingLabels = parseBindingLabels(fs.readFileSync(path.join(root, consumer.source), "utf-8"));
      if (bindingLabels.length === 0) throw new Error(`No BUS bindings found in ${consumer.source}`);
      const { source: _source, ...portable } = consumer;
      return { ...portable, bindingLabels };
    }),
  };
}

async function main() {
  const platform = flag("--platform", normalizedPlatform());
  const arch = flag("--arch", process.arch);
  if (!["windows", "macos"].includes(platform)) throw new Error(`Unsupported package platform: ${platform}`);
  if (!["x64", "arm64"].includes(arch)) throw new Error(`Unsupported package architecture: ${arch}`);
  if (platform !== normalizedPlatform() || arch !== process.arch) {
    throw new Error(`Package target ${platform}-${arch} must be built on the matching host; current host is ${normalizedPlatform()}-${process.arch}`);
  }

  const packageName = `SMC-Onboarding-${platform === "windows" ? "Windows" : "macOS"}-${arch}`;
  const outRoot = path.resolve(flag("--out-dir", path.join(root, "dist", "tv-onboarding")));
  const destination = path.join(outRoot, packageName);
  fs.rmSync(destination, { recursive: true, force: true });
  fs.mkdirSync(path.join(destination, "app"), { recursive: true });
  fs.mkdirSync(path.join(destination, "runtime"), { recursive: true });
  fs.mkdirSync(path.join(destination, "node_modules"), { recursive: true });

  await build({
    entryPoints: [path.join(root, "scripts", "tv_onboard_consumers.ts")],
    outfile: path.join(destination, "app", "tv_onboard_consumers.mjs"),
    bundle: true,
    platform: "node",
    format: "esm",
    target: "node20",
    external: ["playwright"],
    sourcemap: false,
    legalComments: "none",
  });
  fs.writeFileSync(path.join(destination, "app", "consumer-onboarding.json"), `${JSON.stringify(portableConfig(), null, 2)}\n`, "utf-8");
  copyPackage("playwright", path.join(destination, "node_modules", "playwright"));
  copyPackage("playwright-core", path.join(destination, "node_modules", "playwright-core"));

  const runtimeName = platform === "windows" ? "node.exe" : "node";
  const runtimePath = path.join(destination, "runtime", runtimeName);
  fs.copyFileSync(process.execPath, runtimePath);
  if (platform === "macos") fs.chmodSync(runtimePath, 0o755);
  const nodeLicense = findNodeLicense(process.execPath);
  if (!nodeLicense) throw new Error(`Could not locate the Node.js license next to ${process.execPath}`);
  fs.copyFileSync(nodeLicense, path.join(destination, "runtime", "NODE-LICENSE"));

  fs.cpSync(path.join(root, "docs", "tradingview-onboarding"), path.join(destination, "Documentation"), { recursive: true });
  fs.copyFileSync(
    path.join(path.dirname(require.resolve("playwright-core/package.json")), "LICENSE"),
    path.join(destination, "PLAYWRIGHT-LICENSE"),
  );

  if (platform === "windows") {
    fs.writeFileSync(
      path.join(destination, "Start SMC Onboarding.cmd"),
      "@echo off\r\nsetlocal\r\n\"%~dp0runtime\\node.exe\" \"%~dp0app\\tv_onboard_consumers.mjs\" %*\r\nset EXIT_CODE=%ERRORLEVEL%\r\necho.\r\nif not \"%SMC_ONBOARDING_NO_PAUSE%\"==\"1\" pause\r\nexit /b %EXIT_CODE%\r\n",
      "utf-8",
    );
  } else {
    const launcher = path.join(destination, "Start SMC Onboarding.command");
    fs.writeFileSync(
      launcher,
      "#!/bin/sh\nDIR=$(CDPATH= cd -- \"$(dirname -- \"$0\")\" && pwd)\nexec \"$DIR/runtime/node\" \"$DIR/app/tv_onboard_consumers.mjs\" \"$@\"\n",
      "utf-8",
    );
    fs.chmodSync(launcher, 0o755);
  }

  const manifest = {
    schemaVersion: 1,
    packageName,
    platform,
    architecture: arch,
    nodeVersion: process.version,
    requiresNpm: false,
    browserRequirement: "Google Chrome or Microsoft Edge",
    files: filesUnder(destination)
      .map((file) => ({ path: path.relative(destination, file).replaceAll(path.sep, "/"), sha256: sha256(file) }))
      .sort((left, right) => left.path.localeCompare(right.path)),
  };
  fs.writeFileSync(path.join(destination, "package-manifest.json"), `${JSON.stringify(manifest, null, 2)}\n`, "utf-8");
  console.log(JSON.stringify({ ok: true, destination, ...manifest, files: manifest.files.length }));
}

main().catch((error) => {
  console.error(JSON.stringify({ ok: false, error: error instanceof Error ? error.message : String(error) }));
  process.exit(1);
});
