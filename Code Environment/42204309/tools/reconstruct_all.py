#!/usr/bin/env python3
"""Build a composite C_env and replay all selected pre-task repositories.

The generated repositories are evidence-bounded simulations.  The Solidity
toolchain is reduced from an observed deliverable; the web/API shell is a
minimal Node.js implementation inferred from chat evidence because no web or
backend source snapshot was delivered.
"""

from __future__ import annotations

import copy
import hashlib
import html
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import textwrap
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any


WORKSPACE = Path("/workspace/scratch/09ada1f5f2cf")
UPLOAD = WORKSPACE / "upload"
WORK = WORKSPACE / "work"
BUILD_ROOT = WORK / "reconstruction_build_v2"
DELIVERY_ROOT = WORK / "final_delivery_v2"
MASTER_NAME = "42204309_complete_reconstruction"
MASTER_ROOT = DELIVERY_ROOT / MASTER_NAME
GRAPH_PATH = UPLOAD / "requirement_state_graph(5).json"
GOLD_PATH = UPLOAD / "gold_states.json"
STAGE1_PATH = UPLOAD / "42204309_stage1_annotation(8).json"
SAMPLE_ZIP = UPLOAD / "42204309（sample）.zip"
OBSERVED_REPO = (
    WORK
    / "source"
    / "42204309（sample）"
    / "deliverables"
    / "paid_17490607"
    / "projectrebuild-main"
)
OLD_CENV = WORK / "deliverable" / "42204309_C_env" / "project"
DESIGN_DOC = WORK / "Code_State_Reconstruction_Pipeline_Design_v1.md"

CODE_COMPONENTS = {
    "API",
    "AUTH",
    "BACKEND",
    "EMAIL",
    "FRONTEND",
    "INFRASTRUCTURE",
    "PAYMENT",
    "SMART_CONTRACT",
    "STORAGE",
    "UI_UX",
}
EXCLUDED_LIFECYCLES = {"REMOVED", "DEFERRED"}
FORBIDDEN_CENV_PATTERN = re.compile(
    r"project\s*rebuild|booksonchain|referr|commission|prize|pool|small\s*block|"
    r"big\s*block|ticket|winner|vrf|chainlink|aave|usdc|mint|royalt|badge|"
    r"transak|ebook|nft|discord|brevo",
    re.IGNORECASE,
)
SECRET_PATTERN = re.compile(
    r"xkeysib-[A-Za-z0-9_-]+|whsec_[A-Za-z0-9_-]+|"
    r"(?:private[_ -]?key|api[_ -]?key|password)\s*[:=]\s*[^\s,]+",
    re.IGNORECASE,
)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_text(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def write_json(path: Path, value: Any) -> None:
    write_text(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_tree(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(p for p in path.rglob("*") if p.is_file()):
        rel = item.relative_to(path).as_posix()
        if any(part in {"node_modules", "out", "cache", "dist", ".git"} for part in item.parts):
            continue
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(item.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def canonical_digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def safe_slug(requirement_id: str) -> str:
    value = requirement_id.removeprefix("REQ_").lower().replace("_", "-")
    return re.sub(r"[^a-z0-9-]+", "-", value).strip("-")


def js_identifier(slug: str) -> str:
    parts = re.split(r"[^A-Za-z0-9]+", slug)
    return "feature" + "".join(part[:1].upper() + part[1:] for part in parts if part)


def sanitize_string(value: str) -> str:
    value = SECRET_PATTERN.sub("[REDACTED_SECRET]", value)
    value = re.sub(r"0x[a-fA-F0-9]{64}\b", "[REDACTED_TRANSACTION]", value)
    value = re.sub(
        r"0x[a-fA-F0-9]{40}\b",
        "0x0000000000000000000000000000000000000000",
        value,
    )
    return value


def sanitize_value(value: Any, key: str = "") -> Any:
    key_lower = key.lower()
    if isinstance(value, dict):
        return {k: sanitize_value(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_value(v, key) for v in value]
    if isinstance(value, str):
        if any(token in key_lower for token in ("private_key", "secret", "api_key", "password")):
            return "[REDACTED_SECRET]"
        if "address" in key_lower and re.fullmatch(r"0x[a-fA-F0-9]{40}", value):
            return "0x0000000000000000000000000000000000000000"
        return sanitize_string(value)
    return value


def numeric_amount(value: Any, default: int = 0) -> int:
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        match = re.search(r"\$?\s*([0-9][0-9,]*)", value)
        if match:
            return int(match.group(1).replace(",", ""))
    return default


def reset_known_directory(path: Path) -> None:
    resolved = path.resolve()
    if resolved not in {BUILD_ROOT.resolve(), DELIVERY_ROOT.resolve()}:
        raise RuntimeError(f"Refusing to reset unexpected path: {resolved}")
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def copy_package_lock(destination: Path) -> None:
    lock = read_json(OLD_CENV / "package-lock.json")
    lock["name"] = "composite-code-environment"
    lock["version"] = "2.0.0"
    root = lock["packages"][""]
    root["name"] = "composite-code-environment"
    root["version"] = "2.0.0"
    write_json(destination, lock)


def base_package_json() -> dict[str, Any]:
    return {
        "name": "composite-code-environment",
        "version": "2.0.0",
        "private": True,
        "description": "Evidence-bounded runnable application and contract environment",
        "type": "module",
        "scripts": {
            "start": "node apps/server/server.mjs",
            "build:app": "node scripts/build-app.mjs",
            "build:contracts": "forge build --root packages/contracts",
            "build": "npm run build:app && npm run build:contracts",
            "test:app": "node --test tests/*.test.mjs",
            "test:contracts": "forge test --root packages/contracts",
            "test": "npm run test:app && npm run test:contracts",
            "format:contracts": "forge fmt --root packages/contracts --check",
            "check": "npm run format:contracts && npm run build && npm test",
        },
        "engines": {"node": ">=20"},
        "devDependencies": {"@foundry-rs/forge": "1.7.1"},
        "license": "MIT",
    }


SERVER_SOURCE = r'''import http from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";
import { findFeature, snapshot } from "./src/runtime.mjs";

const publicDirectory = fileURLToPath(new URL("../web/public/", import.meta.url));
const contentTypes = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
};

function json(response, status, body) {
  response.writeHead(status, { "content-type": "application/json; charset=utf-8" });
  response.end(JSON.stringify(body));
}

async function staticFile(response, pathname) {
  const requested = pathname === "/" ? "index.html" : pathname.slice(1);
  const safe = normalize(requested).replace(/^(\.\.[/\\])+/, "");
  const file = join(publicDirectory, safe);
  try {
    const body = await readFile(file);
    response.writeHead(200, { "content-type": contentTypes[extname(file)] ?? "application/octet-stream" });
    response.end(body);
  } catch {
    json(response, 404, { error: "not_found" });
  }
}

export function createAppServer() {
  return http.createServer(async (request, response) => {
    const url = new URL(request.url ?? "/", "http://localhost");
    if (url.pathname === "/health") {
      return json(response, 200, { status: "ok", featureCount: snapshot.features.length });
    }
    if (url.pathname === "/api/state") {
      return json(response, 200, snapshot);
    }
    if (url.pathname.startsWith("/api/feature/")) {
      const feature = findFeature(decodeURIComponent(url.pathname.slice("/api/feature/".length)));
      return feature ? json(response, 200, feature) : json(response, 404, { error: "feature_not_found" });
    }
    return staticFile(response, url.pathname);
  });
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const port = Number(process.env.PORT ?? 3000);
  createAppServer().listen(port, "0.0.0.0", () => {
    process.stdout.write(`environment listening on ${port}\n`);
  });
}
'''


NEUTRAL_RUNTIME = r'''export const snapshot = Object.freeze({
  environment: "ready",
  projectName: "Application Shell",
  hero: null,
  features: [],
});

export function findFeature() {
  return null;
}
'''


NEUTRAL_HTML = r'''<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Application Shell</title>
    <link rel="stylesheet" href="/styles.css">
  </head>
  <body>
    <main id="app" class="shell" aria-live="polite">
      <p class="eyebrow">Runtime status</p>
      <h1>Application Shell</h1>
      <p>The web and API environment is ready.</p>
    </main>
    <script type="module" src="/app.js"></script>
  </body>
</html>
'''


APP_JS = r'''const root = document.querySelector("#app");

function valueText(value) {
  if (Array.isArray(value)) return value.map(valueText).join(" · ");
  if (value && typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function renderFeature(feature) {
  const items = Object.entries(feature.configuration)
    .slice(0, 8)
    .map(([key, value]) => `<li><strong>${key.replaceAll("_", " ")}</strong><span>${valueText(value)}</span></li>`)
    .join("");
  return `<article class="feature"><p>${feature.family || "Current capability"}</p><h2>${feature.title}</h2><ul>${items}</ul></article>`;
}

async function boot() {
  const response = await fetch("/api/state");
  const state = await response.json();
  if (!state.features.length) return;
  document.title = state.projectName;
  const hero = state.hero
    ? `<section class="hero"><div><p class="eyebrow">Current application</p><h1>${state.hero.headline_text || state.projectName}</h1><p>${state.hero.subheadline_text || ""}</p><a class="button" href="#features">${state.hero.cta_text || "Explore"}</a></div><div class="cover" aria-label="Current cover presentation"><span>BOOK</span></div></section>`
    : `<header><p class="eyebrow">Current application</p><h1>${state.projectName}</h1></header>`;
  root.innerHTML = `${hero}<section id="features" class="features">${state.features.map(renderFeature).join("")}</section>`;
}

boot().catch((error) => {
  root.innerHTML = `<h1>Application unavailable</h1><pre>${error.message}</pre>`;
});
'''


BASE_CSS = r''':root {
  color-scheme: dark;
  font-family: Inter, ui-sans-serif, system-ui, sans-serif;
  background: #0d1721;
  color: #ecf4f4;
}
* { box-sizing: border-box; }
body { margin: 0; min-height: 100vh; background: radial-gradient(circle at top right, #19414a, #0d1721 48%); }
.shell { width: min(1120px, calc(100% - 32px)); margin: 0 auto; padding: 72px 0; }
.eyebrow, .feature > p { color: #7ee0c3; font-size: .78rem; font-weight: 800; letter-spacing: .12em; text-transform: uppercase; }
h1 { max-width: 16ch; margin: .2em 0; font-size: clamp(2.5rem, 7vw, 5.2rem); line-height: .98; }
.hero { position: relative; display: grid; grid-template-columns: minmax(0, 1.6fr) minmax(180px, .6fr); gap: 48px; align-items: center; min-height: 430px; }
.hero p { max-width: 66ch; color: #b9cccf; line-height: 1.6; }
.button { display: inline-block; margin-top: 18px; padding: 12px 18px; border-radius: 999px; background: #7ee0c3; color: #102228; font-weight: 800; text-decoration: none; }
.cover { aspect-ratio: 2 / 3; display: grid; place-items: center; border: 1px solid #4b747a; border-radius: 16px; background: linear-gradient(145deg, #24545c, #101d28); box-shadow: 0 24px 60px #0008; }
.cover span { letter-spacing: .28em; color: #b8f8e3; }
.features { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 18px; margin-top: 48px; }
.feature { min-width: 0; padding: 22px; border: 1px solid #29444c; border-radius: 16px; background: #13242dcc; }
.feature h2 { margin: 8px 0 18px; font-size: 1.18rem; }
.feature ul { display: grid; gap: 10px; margin: 0; padding: 0; list-style: none; }
.feature li { display: grid; gap: 3px; overflow-wrap: anywhere; }
.feature li strong { color: #93aaad; font-size: .72rem; text-transform: uppercase; }
.feature li span { color: #e4efef; font-size: .88rem; line-height: 1.45; }
@media (max-width: 700px) {
  .shell { padding-top: 40px; }
  .hero { grid-template-columns: 1fr; }
  .cover { width: min(220px, 68vw); }
}
'''


BUILD_SCRIPT = r'''import { cp, mkdir, rm, writeFile } from "node:fs/promises";
import { snapshot } from "../apps/server/src/runtime.mjs";

await rm("dist", { recursive: true, force: true });
await mkdir("dist", { recursive: true });
await cp("apps/web/public", "dist/public", { recursive: true });
await writeFile("dist/build.json", `${JSON.stringify({ featureCount: snapshot.features.length })}\n`);
process.stdout.write(`web build complete (${snapshot.features.length} current features)\n`);
'''


SMOKE_TEST = r'''import assert from "node:assert/strict";
import test from "node:test";
import { once } from "node:events";
import { createAppServer } from "../apps/server/server.mjs";
import { snapshot } from "../apps/server/src/runtime.mjs";

test("runtime snapshot is loadable", () => {
  assert.equal(Array.isArray(snapshot.features), true);
});

test("health and root routes respond", async (context) => {
  const server = createAppServer();
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  context.after(() => server.close());
  const address = server.address();
  const base = `http://127.0.0.1:${address.port}`;
  const health = await fetch(`${base}/health`);
  assert.equal(health.status, 200);
  assert.equal((await health.json()).status, "ok");
  const root = await fetch(base);
  assert.equal(root.status, 200);
  assert.match(await root.text(), /Application Shell/);
});
'''


ENVIRONMENT_SOL = r'''// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

/// @notice Minimal deployable contract used only to verify the Solidity toolchain.
contract Environment { }
'''


ENVIRONMENT_TEST = r'''// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import { Environment } from "../contracts/Environment.sol";

contract EnvironmentSmoke {
    function testDeploysMinimalContract() public {
        Environment instance = new Environment();
        assert(address(instance) != address(0));
        assert(address(instance).code.length > 0);
    }
}
'''


FOUNDRY_TOML = r'''[profile.default]
src = "contracts"
test = "test"
script = "script"
out = "out"
cache_path = "cache"
libs = []
solc_version = "0.8.24"
optimizer = true
optimizer_runs = 200
via_ir = false
evm_version = "paris"

[profile.ci.fuzz]
runs = 10000

[profile.ci.invariant]
runs = 1000

[fmt]
line_length = 120
tab_width = 4
bracket_spacing = true
int_types = "long"
multiline_func_header = "all"
quote_style = "double"
number_underscore = "thousands"
'''


def create_base_repo(destination: Path, cenv: bool) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    write_json(destination / "package.json", base_package_json())
    copy_package_lock(destination / "package-lock.json")
    write_text(destination / ".gitignore", "node_modules/\ndist/\nout/\ncache/\n.env\n")
    write_text(destination / ".dockerignore", "node_modules\ndist\nout\ncache\n.git\n")
    write_text(destination / ".env.example", "PORT=3000\n")
    write_text(
        destination / "Dockerfile",
        textwrap.dedent(
            """\
            FROM node:22-bookworm-slim
            WORKDIR /workspace
            COPY package.json package-lock.json ./
            RUN npm ci
            COPY . .
            ENV PORT=3000
            EXPOSE 3000
            CMD ["npm", "start"]
            """
        ),
    )
    write_text(
        destination / "Makefile",
        ".PHONY: install build test start check clean\n"
        "install:\n\tnpm ci\n"
        "build:\n\tnpm run build\n"
        "test:\n\tnpm test\n"
        "start:\n\tnpm start\n"
        "check:\n\tnpm run check\n"
        "clean:\n\trm -rf dist packages/contracts/out packages/contracts/cache\n",
    )
    write_text(destination / "apps/server/server.mjs", SERVER_SOURCE)
    write_text(destination / "apps/server/src/runtime.mjs", NEUTRAL_RUNTIME)
    write_text(destination / "apps/web/public/index.html", NEUTRAL_HTML)
    write_text(destination / "apps/web/public/app.js", APP_JS)
    write_text(destination / "apps/web/public/styles.css", BASE_CSS)
    write_text(destination / "scripts/build-app.mjs", BUILD_SCRIPT)
    write_text(destination / "tests/smoke.test.mjs", SMOKE_TEST)
    write_text(destination / "packages/contracts/foundry.toml", FOUNDRY_TOML)
    write_text(destination / "packages/contracts/contracts/Environment.sol", ENVIRONMENT_SOL)
    write_text(destination / "packages/contracts/test/EnvironmentSmoke.t.sol", ENVIRONMENT_TEST)
    if cenv:
        write_text(
            destination / "README.md",
            textwrap.dedent(
                """\
                # Composite Code Environment

                This is a runnable, zero-domain application shell. It preserves the observed
                Solidity/Foundry build chain and adds a neutral web/API process so later
                repository states can be replayed consistently.

                ```bash
                npm ci
                npm run check
                npm start
                curl http://localhost:3000/health
                ```

                The web/API shell is simulated because no corresponding source snapshot was
                delivered. It intentionally exposes only a health endpoint and a generic
                state endpoint.
                """
            ),
        )
    else:
        write_text(
            destination / "README.md",
            textwrap.dedent(
                """\
                # Reconstructed Application Snapshot

                This repository is an evidence-bounded, runnable simulation of one historical
                pre-event code state. It contains only behavior and configuration supported at
                this boundary; later event instructions are not embedded.

                ```bash
                npm ci
                npm run check
                npm start
                ```

                The contract toolchain is evidence-backed. The web/API implementation is a
                deterministic simulation because its historical source repository was absent.
                """
            ),
        )


def feature_module(requirement: dict[str, Any], node: dict[str, Any]) -> str:
    scope = node.get("scope") or {}
    payload = {
        "key": safe_slug(requirement["requirement_id"]),
        "title": requirement.get("title") or safe_slug(requirement["requirement_id"]),
        "family": requirement.get("family_id") or "CURRENT_CAPABILITY",
        "components": sorted(set(scope.get("components") or [])),
        "contexts": sorted(set(scope.get("contexts") or [])),
        "configuration": sanitize_value(node.get("attributes") or {}),
    }
    return "export default Object.freeze(" + json.dumps(payload, ensure_ascii=False, indent=2) + ");\n"


def state_runtime(imports: list[tuple[str, str]], project_name: str, hero: dict[str, Any] | None) -> str:
    import_lines = [f'import {ident} from "./features/{slug}.mjs";' for ident, slug in imports]
    identifiers = ", ".join(ident for ident, _ in imports)
    return (
        "\n".join(import_lines)
        + "\n\n"
        + f"const features = Object.freeze([{identifiers}]);\n"
        + f"const hero = {json.dumps(sanitize_value(hero), ensure_ascii=False, indent=2) if hero else 'null'};\n\n"
        + "export const snapshot = Object.freeze({\n"
        + "  environment: \"reconstructed-pre-event\",\n"
        + f"  projectName: {json.dumps(sanitize_string(project_name), ensure_ascii=False)},\n"
        + "  hero,\n"
        + "  features,\n"
        + "});\n\n"
        + "export function findFeature(key) {\n"
        + "  return features.find((feature) => feature.key === key) ?? null;\n"
        + "}\n"
    )


def make_contract_model(
    current: dict[str, str],
    graph_by_id: dict[str, dict[str, Any]],
    node_by_state: dict[str, dict[str, Any]],
    active_code_requirements: list[str],
) -> tuple[str, str]:
    def attrs(requirement_id: str) -> dict[str, Any]:
        state_id = current.get(requirement_id)
        return sanitize_value(node_by_state.get(state_id, {}).get("attributes") or {})

    pricing = attrs("REQ_MINT_PRICE_AND_REVENUE_SPLIT")
    referral = attrs("REQ_REFERRAL_COMMISSION")
    small = attrs("REQ_SMALL_BLOCK_PRIZE")
    big_state = current.get("REQ_BIG_BLOCK_PRIZE")
    big_node = node_by_state.get(big_state, {})
    big_enabled = bool(big_state and big_node.get("lifecycle_status") not in EXCLUDED_LIFECYCLES)
    claim = attrs("REQ_PRIZE_CLAIM_FLOW")
    manual_claim = (
        claim.get("prize_collection_mode") == "manual_claim"
        or claim.get("prize_delivery_mode") == "manual_claim"
    )
    mint_price = numeric_amount(pricing.get("mint_price_usd"), 0)
    founder = numeric_amount(pricing.get("founder_share_per_primary_sale_usd"), 0)
    commission = numeric_amount(
        pricing.get("commission_share_per_primary_sale_usd", referral.get("commission_amount")),
        0,
    )
    small_prize = numeric_amount(small.get("prize_amount_per_winner"), 0)
    sales_per_draw = numeric_amount(small.get("sales_per_draw"), 0)
    digest_payload = {
        rid: sanitize_value(node_by_state[current[rid]].get("attributes") or {})
        for rid in active_code_requirements
        if "SMART_CONTRACT" in set((node_by_state[current[rid]].get("scope") or {}).get("components") or [])
    }
    digest = canonical_digest(digest_payload)
    source = textwrap.dedent(
        f'''\
        // SPDX-License-Identifier: MIT
        pragma solidity 0.8.24;

        /// @notice Executable model of the currently reconstructed contract-facing configuration.
        contract ProjectStateModel {{
            uint256 public constant FEATURE_COUNT = {len(active_code_requirements)};
            uint256 public constant MINT_PRICE_USD = {mint_price};
            uint256 public constant FOUNDER_SHARE_USD = {founder};
            uint256 public constant COMMISSION_USD = {commission};
            uint256 public constant SMALL_PRIZE_USD = {small_prize};
            uint256 public constant SALES_PER_DRAW = {sales_per_draw};
            bool public constant BIG_BLOCK_ENABLED = {str(big_enabled).lower()};
            bool public constant MANUAL_PRIZE_CLAIM = {str(manual_claim).lower()};
            bytes32 public constant CONFIGURATION_DIGEST =
                hex"{digest}";

            function isReferralCodeValid(uint256 code, uint256 mintedSupply) external pure returns (bool) {{
                return code > 0 && code <= mintedSupply;
            }}
        }}
        '''
    )
    test = textwrap.dedent(
        f'''\
        // SPDX-License-Identifier: MIT
        pragma solidity 0.8.24;

        import {{ ProjectStateModel }} from "../contracts/ProjectStateModel.sol";

        contract ProjectStateModelSmoke {{
            function testCurrentModelLoads() public {{
                ProjectStateModel model = new ProjectStateModel();
                assert(model.FEATURE_COUNT() == {len(active_code_requirements)});
                assert(model.CONFIGURATION_DIGEST() != bytes32(0));
            }}

            function testReferralBoundary() public {{
                ProjectStateModel model = new ProjectStateModel();
                assert(!model.isReferralCodeValid(0, 10));
                assert(model.isReferralCodeValid(1, 10));
                assert(!model.isReferralCodeValid(11, 10));
            }}
        }}
        '''
    )
    return source, test


def inject_temporal_fixture(repo: Path, target_id: str) -> str | None:
    if target_id == "42204309_T008":
        with (repo / "apps/web/public/styles.css").open("a", encoding="utf-8") as handle:
            handle.write(
                "\n/* Historical implementation shape retained at this boundary. */\n"
                ".hero h1 { font-size: clamp(5.5rem, 11vw, 9rem); max-width: 11ch; }\n"
                ".hero .cover { position: absolute; right: 0; top: 0; width: 52%; z-index: 3; }\n"
                "@media (max-width: 700px) { .hero .cover { width: 80%; right: -24%; } }\n"
            )
        return "layout_overlap_seed"
    if target_id == "42204309_T010":
        write_text(
            repo / "apps/server/src/ledger.mjs",
            textwrap.dedent(
                '''\
                export function listOwnedAssets(rows, account) {
                  return rows.filter((row) => row.account === account);
                }

                export function dashboardCount(rows, account) {
                  return listOwnedAssets(rows, account).length;
                }
                '''
            ),
        )
        write_json(
            repo / "data/local-ledger.json",
            [
                {"account": "local-user", "tokenId": 1, "confirmed": True},
                {"account": "local-user", "tokenId": 2, "confirmed": False},
                {"account": "local-user", "tokenId": 3, "confirmed": False},
            ],
        )
        return "unconfirmed_rows_counted_seed"
    if target_id == "42204309_T020":
        write_text(
            repo / "apps/server/src/accounting.mjs",
            textwrap.dedent(
                '''\
                export function leaderboardTotals(ledger) {
                  return ledger.reduce((total, row) => ({
                    tickets: total.tickets + row.tickets,
                    commissions: total.commissions + row.commissions,
                  }), { tickets: 0, commissions: 0 });
                }

                export function metadataAttributes(cachedMetadata) {
                  return cachedMetadata.attributes;
                }
                '''
            ),
        )
        write_json(
            repo / "data/local-accounting.json",
            {
                "ledger": [{"tokenId": 1, "tickets": 11, "commissions": 11}],
                "cachedMetadata": {
                    "tokenId": 1,
                    "attributes": {"tickets": 11, "commissions": 10},
                },
            },
        )
        return "stale_metadata_seed"
    return None


def create_state_repo(
    destination: Path,
    target: dict[str, Any],
    current: dict[str, str],
    graph_by_id: dict[str, dict[str, Any]],
    node_by_state: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    create_base_repo(destination, cenv=False)
    active_code_requirements: list[str] = []
    mappings: list[dict[str, Any]] = []
    imports: list[tuple[str, str]] = []
    project_name = "Application"
    hero: dict[str, Any] | None = None

    for requirement_id in sorted(current):
        requirement = graph_by_id[requirement_id]
        state_id = current[requirement_id]
        node = node_by_state[state_id]
        scope = node.get("scope") or {}
        components = sorted(set(scope.get("components") or []))
        lifecycle = node.get("lifecycle_status") or "ACTIVE"
        slug = safe_slug(requirement_id)
        code_capable = bool(set(components) & CODE_COMPONENTS)
        current_active = lifecycle not in EXCLUDED_LIFECYCLES
        paths: list[str] = []
        mode = "excluded_lifecycle"

        if current_active and code_capable:
            module_path = destination / "apps/server/src/features" / f"{slug}.mjs"
            write_text(module_path, feature_module(requirement, node))
            ident = js_identifier(slug)
            imports.append((ident, slug))
            active_code_requirements.append(requirement_id)
            paths.append(f"apps/server/src/features/{slug}.mjs")
            mode = "simulated_executable"
            if "FRONTEND" in components or "UI_UX" in components:
                paths.extend(["apps/web/public/app.js", "apps/web/public/styles.css"])
            if "SMART_CONTRACT" in components:
                paths.append("packages/contracts/contracts/ProjectStateModel.sol")
        elif current_active and not code_capable:
            mode = "non_code_action"

        attrs = sanitize_value(node.get("attributes") or {})
        if requirement_id == "REQ_PROJECT_BRANDING":
            project_name = attrs.get("current_product_name", project_name)
        if requirement_id == "REQ_LANDING_HERO_PRESENTATION" and current_active:
            hero = attrs
        mappings.append(
            {
                "requirement_id": requirement_id,
                "state_id": state_id,
                "lifecycle": lifecycle,
                "components": components,
                "implementation_mode": mode,
                "code_paths": sorted(set(paths)),
            }
        )

    imports.sort(key=lambda item: item[1])
    write_text(destination / "apps/server/src/runtime.mjs", state_runtime(imports, project_name, hero))
    model, model_test = make_contract_model(
        current, graph_by_id, node_by_state, active_code_requirements
    )
    write_text(destination / "packages/contracts/contracts/ProjectStateModel.sol", model)
    write_text(destination / "packages/contracts/test/ProjectStateModelSmoke.t.sol", model_test)
    temporal_fixture = inject_temporal_fixture(destination, target["target_id"])
    return {
        "target_id": target["target_id"],
        "before_message_id": target["conversation_turn_index"],
        "repository_classification": "simulated-executable-pre-state",
        "contract_layer": "observed-toolchain-plus-simulated-state-model",
        "web_api_layer": "simulated-from-chat-and-state-graph",
        "active_code_feature_count": len(active_code_requirements),
        "tracked_requirement_count": len(current),
        "temporal_fixture": temporal_fixture,
        "requirements_to_code": mappings,
    }


def zip_directory(source: Path, output: Path, root_name: str | None = None) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    excluded_parts = {"node_modules", "dist", "out", "cache", ".git", "__pycache__"}
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(p for p in source.rglob("*") if p.is_file()):
            if excluded_parts & set(path.relative_to(source).parts):
                continue
            rel = path.relative_to(source)
            arcname = Path(root_name) / rel if root_name else rel
            archive.write(path, arcname.as_posix())


def compare_state(actual: dict[str, str], expected_rows: list[dict[str, str]], label: str) -> None:
    expected = {row["requirement_id"]: row["state_id"] for row in expected_rows}
    if actual != expected:
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        changed = sorted(k for k in set(actual) & set(expected) if actual[k] != expected[k])
        raise AssertionError(
            f"{label} mismatch: missing={missing}, extra={extra}, changed={changed[:12]}"
        )


def source_checksums() -> dict[str, Any]:
    files = [GRAPH_PATH, GOLD_PATH, STAGE1_PATH, SAMPLE_ZIP]
    return {
        "files": [
            {"name": path.name, "sha256": sha256_file(path), "size_bytes": path.stat().st_size}
            for path in files
        ],
        "observed_contract_repository_tree_sha256": sha256_tree(OBSERVED_REPO),
    }


def create_cenv(project: Path, audit: Path) -> dict[str, Any]:
    create_base_repo(project, cenv=True)
    manifest = {
        "schema_version": "2.0",
        "project_id": "42204309",
        "baseline_type": "hybrid-reduced-and-simulated",
        "scope": "project-level composite code environment",
        "boundary": "C_env; zero benchmark-domain behavior; not C_start",
        "source_snapshot": {
            "label": "C_obs_contract_milestone_paid_17490607",
            "sample_zip_sha256": sha256_file(SAMPLE_ZIP),
            "contract_repository_tree_sha256": sha256_tree(OBSERVED_REPO),
            "confidence": "A for contract toolchain; C/E for web/API shell",
        },
        "toolchain": {
            "observed": {
                "contract_language": "Solidity 0.8.24",
                "contract_framework": "Foundry",
                "forge_package": "@foundry-rs/forge 1.7.1",
                "container_and_make_wrappers": True,
            },
            "inferred": {
                "product_layers": ["web frontend", "backend API", "database-backed service"],
                "deployment_style": "VPS-hosted web and API services",
            },
            "assumed": {
                "web_api_runtime": "Node.js >=20 using standard-library HTTP only",
                "reason": "No frontend/backend repository or framework-identifying lockfile was delivered.",
            },
        },
        "commands": {
            "install": "npm ci",
            "build": "npm run build",
            "test": "npm test",
            "run": "npm start",
            "full_check": "npm run check",
        },
        "artifacts": [
            {
                "path": "packages/contracts",
                "action": "replace",
                "reason": "Preserve observed Foundry/Solc build chain while replacing domain contracts with a neutral deployable entry.",
            },
            {
                "path": "apps/server",
                "action": "synthesize",
                "reason": "Provide a neutral health/API process for a product layer proven by chat but absent from delivered source.",
            },
            {
                "path": "apps/web",
                "action": "synthesize",
                "reason": "Provide a neutral static application shell without domain pages or workflows.",
            },
            {
                "path": "tests",
                "action": "replace",
                "reason": "Keep only environment smoke tests.",
            },
        ],
        "known_limitations": [
            "This is not a historical original repository commit.",
            "The observed deliverable covers the smart-contract milestone only.",
            "The web/API runtime is deliberately minimal and simulated.",
        ],
    }
    write_json(audit / "cenv_manifest.json", manifest)
    write_json(
        audit / "artifact_decisions.json",
        {
            "kept": ["Solidity version", "Foundry directory conventions", "forge package lock", "Docker/Make entry points"],
            "reset": ["root scripts", "README", "container command", "test boundary"],
            "deleted": ["all observed domain contracts", "domain interfaces", "domain mocks", "domain tests", "domain deployment configuration"],
            "synthesized": ["neutral Node.js web/API shell", "neutral web page", "HTTP and EVM smoke tests"],
        },
    )
    return manifest


def run_command(command: list[str], cwd: Path, env: dict[str, str] | None = None) -> dict[str, Any]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    result = subprocess.run(
        command,
        cwd=cwd,
        env=merged_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=180,
        check=False,
    )
    return {
        "command": " ".join(command),
        "cwd": str(cwd),
        "exit_code": result.returncode,
        "output_tail": result.stdout[-4000:],
    }


def validate_outputs(cenv_project: Path, target_repos: list[Path]) -> dict[str, Any]:
    validations: list[dict[str, Any]] = []
    validations.append(run_command(["npm", "ci"], cenv_project))
    validations.append(run_command(["npm", "run", "check"], cenv_project))
    forge = cenv_project / "node_modules" / ".bin" / "forge"
    for repo in target_repos:
        app_build = run_command(["node", "scripts/build-app.mjs"], repo)
        app_test = run_command(["node", "--test", "tests/smoke.test.mjs"], repo)
        contract_format = run_command([str(forge), "fmt", "--root", "packages/contracts", "--check"], repo)
        contract_build = run_command([str(forge), "build", "--root", "packages/contracts"], repo)
        contract_test = run_command([str(forge), "test", "--root", "packages/contracts"], repo)
        checks = [app_build, app_test, contract_format, contract_build, contract_test]
        format_clean = contract_format["exit_code"] == 0 and "Diff in " not in contract_format["output_tail"]
        validations.append(
            {
                "repository": repo.name,
                "checks": checks,
                "status": "pass"
                if format_clean and all(item["exit_code"] == 0 for item in checks)
                else "fail",
            }
        )
    cenv_hits: list[dict[str, Any]] = []
    for path in sorted(p for p in cenv_project.rglob("*") if p.is_file()):
        if {"node_modules", "dist", "out", "cache"} & set(path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        matches = sorted(set(match.group(0) for match in FORBIDDEN_CENV_PATTERN.finditer(text)))
        if matches:
            cenv_hits.append({"path": str(path.relative_to(cenv_project)), "matches": matches})
    secret_hits: list[str] = []
    roots = [cenv_project, *target_repos]
    for root in roots:
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            if {"node_modules", "dist", "out", "cache"} & set(path.parts):
                continue
            if SECRET_PATTERN.search(path.read_text(encoding="utf-8", errors="ignore")):
                secret_hits.append(str(path))
    all_commands_pass = all(
        (entry.get("exit_code") == 0 if "exit_code" in entry else entry.get("status") == "pass")
        for entry in validations
    )
    return {
        "overall": "pass" if all_commands_pass and not cenv_hits and not secret_hits else "fail",
        "command_validations": validations,
        "cenv_forbidden_scan": {"status": "pass" if not cenv_hits else "fail", "hits": cenv_hits},
        "secret_scan": {"status": "pass" if not secret_hits else "fail", "hits": secret_hits},
        "common_lockfile_sha256": sha256_file(cenv_project / "package-lock.json"),
    }


def short_target_text(target: dict[str, Any]) -> str:
    text = html.unescape(target["target_task"]["text"])
    text = re.sub(r"\s+", " ", sanitize_string(text)).strip()
    return text[:180] + ("…" if len(text) > 180 else "")


def build_report(target_index: list[dict[str, Any]], replay: dict[str, Any], validation: dict[str, Any]) -> str:
    rows = []
    for item in target_index:
        rows.append(
            f"| {item['target_id'].split('_')[-1]} | {item['before_message_id']} | "
            f"{item['tracked_requirement_count']} | {item['active_code_feature_count']} | "
            f"{item.get('temporal_fixture') or '—'} | `{item['repo_sha256'][:12]}` |"
        )
    report = textwrap.dedent(
        f'''\
        # 42204309 Complete Code-State Reconstruction

        ## Outcome

        This package contains one completed composite `C_env` and 25 independently
        consumable repositories representing `C(t⁻)` for every selected target in
        `gold_states.json`. The state sequence was produced by replaying every event
        group in message order and checking the selected pre/post boundaries against
        the gold state maps.

        ## Evidence classification

        - Smart-contract environment: reduced from an observed Solidity/Foundry
          milestone snapshot (high confidence for toolchain, not a final full product).
        - Web/API environment: executable simulation based on chat evidence and the
          requirement state graph because no frontend/backend source was delivered.
        - External platform work: represented as `non_code_action`; no fake repository
          implementation is introduced.
        - Secrets and production identifiers: excluded or replaced by local placeholders.

        ## Replay audit

        - Event count: {replay['event_count']}
        - Event-group count: {replay['event_group_count']}
        - Selected pre-boundaries matched: {replay['pre_matches']}/25
        - Selected post-boundaries matched: {replay['post_matches']}/25
        - Same-message events were applied atomically after exporting the pre-state.

        ## Target inventory

        | Target | Before message | Tracked states | Executable code features | Seeded historical defect | Repo SHA-256 |
        | --- | ---: | ---: | ---: | --- | --- |
        TARGET_ROWS

        `T008`, `T010`, and `T020` contain narrowly scoped historical defect shapes so
        the target request can operate on a meaningful failing predecessor. Public
        smoke tests verify only environment integrity and do not reveal the required fix.

        ## Validation

        Overall validation: **{validation['overall'].upper()}**.

        Every repository passed its Node build, HTTP smoke test, Foundry compile, and
        Foundry test using the common locked toolchain. The composite `C_env` also
        passed a negative domain-term scan. All generated repositories passed the
        secret-pattern scan.

        ## Important limitation

        These are benchmark construction artifacts, not claimed historical Git commits.
        They are temporally consistent, executable reconstructions. Exact production UI,
        database schema, and backend framework cannot be recovered from the supplied
        evidence because those source files are absent.
        '''
    )
    return report.replace("TARGET_ROWS", os.linesep.join(rows))


def main() -> int:
    reset_known_directory(BUILD_ROOT)
    reset_known_directory(DELIVERY_ROOT)
    MASTER_ROOT.mkdir(parents=True, exist_ok=True)
    (MASTER_ROOT / "C_env").mkdir(parents=True, exist_ok=True)
    (MASTER_ROOT / "targets").mkdir(parents=True, exist_ok=True)
    (MASTER_ROOT / "reports").mkdir(parents=True, exist_ok=True)
    (MASTER_ROOT / "tools").mkdir(parents=True, exist_ok=True)

    graph = read_json(GRAPH_PATH)
    gold = read_json(GOLD_PATH)
    graphs = graph["requirement_graphs"]
    graph_by_id = {item["requirement_id"]: item for item in graphs}
    node_by_state: dict[str, dict[str, Any]] = {}
    for requirement in graphs:
        for node in requirement["nodes"]:
            node_by_state[node["state_id"]] = node

    targets_by_message = {
        target["conversation_turn_index"]: target for target in gold["task_gold_states"]
    }
    events_by_message: dict[int, list[dict[str, Any]]] = defaultdict(list)
    event_count = 0
    for graph_index, requirement in enumerate(graphs):
        for edge_index, edge in enumerate(requirement["edges"]):
            event = copy.deepcopy(edge)
            event["requirement_id"] = requirement["requirement_id"]
            event["graph_index"] = graph_index
            event["edge_index"] = edge_index
            events_by_message[int(event["source_message_id"])].append(event)
            event_count += 1
    for events in events_by_message.values():
        events.sort(key=lambda item: (item["graph_index"], item["edge_index"]))

    cenv_root = BUILD_ROOT / "cenv"
    cenv_project = cenv_root / "project"
    cenv_audit = cenv_root / "reconstruction_audit"
    create_cenv(cenv_project, cenv_audit)

    current: dict[str, str] = {}
    target_repos: list[Path] = []
    target_index: list[dict[str, Any]] = []
    replay_groups: list[dict[str, Any]] = []
    pre_matches = 0
    post_matches = 0

    for message_id in sorted(events_by_message):
        target = targets_by_message.get(message_id)
        if target:
            compare_state(
                current,
                target["pre_task_gold_state"]["requirement_states"],
                f"{target['target_id']} pre",
            )
            pre_matches += 1
            target_folder = f"{target['target_id'].split('_')[-1]}_before_{message_id}"
            repo = BUILD_ROOT / "targets" / target_folder / "project"
            target_manifest = create_state_repo(repo, target, current, graph_by_id, node_by_state)
            target_repos.append(repo)
            target_manifest["target_event_ids"] = target["task_event_ids"]
            target_manifest["target_event_types"] = [
                event["event_type"]
                for event in events_by_message[message_id]
                if event["event_id"] in set(target["task_event_ids"])
            ]
            target_manifest["target_summary"] = short_target_text(target)
            target_manifest["pre_state_verified_against_gold"] = True
            target_manifest["post_state_verified_against_gold"] = False
            target_manifest["repo_sha256"] = sha256_tree(repo)
            target_output = MASTER_ROOT / "targets" / target_folder
            target_output.mkdir(parents=True, exist_ok=True)
            zip_directory(repo, target_output / "pre_repo.zip")
            write_json(target_output / "manifest.json", target_manifest)
            target_index.append(target_manifest)

        transitions: list[dict[str, Any]] = []
        for event in events_by_message[message_id]:
            requirement_id = event["requirement_id"]
            from_state = event.get("from_state_id")
            existing = current.get(requirement_id)
            if existing != from_state:
                raise AssertionError(
                    f"Replay mismatch before {event['event_id']}: expected {from_state}, got {existing}"
                )
            current[requirement_id] = event["to_state_id"]
            transitions.append(
                {
                    "requirement_id": requirement_id,
                    "event_id": event["event_id"],
                    "event_type": event["event_type"],
                    "from_state_id": from_state,
                    "to_state_id": event["to_state_id"],
                }
            )
        replay_groups.append({"message_id": message_id, "events": transitions})

        if target:
            compare_state(
                current,
                target["post_task_gold_state"]["requirement_states"],
                f"{target['target_id']} post",
            )
            post_matches += 1
            target_index[-1]["post_state_verified_against_gold"] = True
            target_folder = f"{target['target_id'].split('_')[-1]}_before_{message_id}"
            write_json(MASTER_ROOT / "targets" / target_folder / "manifest.json", target_index[-1])

    replay_manifest = {
        "schema_version": "2.0",
        "project_id": "42204309",
        "event_count": event_count,
        "event_group_count": len(events_by_message),
        "pre_matches": pre_matches,
        "post_matches": post_matches,
        "atomic_group_rule": "Export C(t-) before applying every edge with source_message_id=t; then apply the entire group.",
        "event_groups": replay_groups,
    }

    validation = validate_outputs(cenv_project, target_repos)
    write_json(cenv_audit / "validation_report.json", validation)
    if validation["overall"] != "pass":
        write_json(WORK / "reconstruction_validation_failure.json", validation)
        raise RuntimeError("Validation failed; see work/reconstruction_validation_failure.json")

    cenv_zip = MASTER_ROOT / "C_env" / "42204309_C_env_complete.zip"
    zip_directory(cenv_root, cenv_zip, root_name="42204309_C_env_complete")
    write_json(MASTER_ROOT / "reports" / "replay_manifest.json", replay_manifest)
    write_json(MASTER_ROOT / "reports" / "target_index.json", target_index)
    write_json(MASTER_ROOT / "reports" / "source_checksums.json", source_checksums())
    write_json(MASTER_ROOT / "reports" / "validation_report.json", validation)
    write_text(
        MASTER_ROOT / "reports" / "reconstruction_report.md",
        build_report(target_index, replay_manifest, validation),
    )
    if DESIGN_DOC.exists():
        shutil.copy2(DESIGN_DOC, MASTER_ROOT / "reports" / DESIGN_DOC.name)
    shutil.copy2(Path(__file__), MASTER_ROOT / "tools" / Path(__file__).name)
    write_text(
        MASTER_ROOT / "README.md",
        textwrap.dedent(
            '''\
            # 42204309 Reconstruction Package

            Start with `reports/reconstruction_report.md`.

            - `C_env/42204309_C_env_complete.zip`: completed zero-domain baseline.
            - `targets/Txxx_before_<message>/pre_repo.zip`: runnable pre-event repository.
            - `targets/.../manifest.json`: state-to-code mapping and boundary audit.
            - `reports/replay_manifest.json`: complete atomic event replay ledger.
            - `reports/validation_report.json`: build, test, leakage, and secret checks.
            - `tools/reconstruct_all.py`: deterministic reconstruction generator.
            '''
        ),
    )

    master_zip = DELIVERY_ROOT / f"{MASTER_NAME}.zip"
    zip_directory(MASTER_ROOT, master_zip, root_name=MASTER_NAME)
    write_json(
        DELIVERY_ROOT / "delivery_summary.json",
        {
            "master_zip": str(master_zip),
            "sha256": sha256_file(master_zip),
            "size_bytes": master_zip.stat().st_size,
            "cenv_zip_sha256": sha256_file(cenv_zip),
            "target_count": len(target_index),
            "validation": validation["overall"],
        },
    )
    print(json.dumps(read_json(DELIVERY_ROOT / "delivery_summary.json"), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
