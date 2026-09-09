import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { createServer } from "../apps/server/server.mjs";
import { diagnostics, featuresForPlatform, openQuestions, snapshot } from "../apps/mobile/src/runtime.mjs";

let server;
let origin;

before(async () => {
  server = createServer();
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  origin = "http://127.0.0.1:" + server.address().port;
});

after(async () => {
  if (server) await new Promise((resolve) => server.close(resolve));
});

test("runtime has unique, valid capability keys", () => {
  const keys = snapshot.features.map((feature) => feature.key);
  assert.equal(new Set(keys).size, keys.length);
  assert.ok(snapshot.features.every((feature) => /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(feature.key)));
});

test("platform projections only contain known capabilities", () => {
  const known = new Set(snapshot.features);
  for (const platform of ["android", "ios"]) assert.ok(featuresForPlatform(platform).every((feature) => known.has(feature)));
  assert.deepEqual(featuresForPlatform("unknown"), []);
});

test("diagnostics and open questions are projected from the reconstructed state", () => {
  assert.deepEqual(diagnostics().map((item) => item.key), snapshot.features.filter((feature) => feature.execution).map((feature) => feature.key));
  assert.equal(openQuestions().length, snapshot.features.reduce((count, feature) => count + feature.ambiguities.length, 0));
});

test("health and snapshot endpoints are runnable", async () => {
  const health = await fetch(origin + "/health");
  assert.equal(health.status, 200);
  assert.deepEqual(await health.json(), { status: "ok" });
  const response = await fetch(origin + "/api/snapshot");
  assert.equal(response.status, 200);
  const body = await response.json();
  assert.equal(body.features.length, snapshot.features.length);
  const diagnosticResponse = await fetch(origin + "/api/diagnostics");
  assert.equal(diagnosticResponse.status, 200);
  assert.deepEqual((await diagnosticResponse.json()).diagnostics, diagnostics());
});

test("static shell is served", async () => {
  const response = await fetch(origin);
  assert.equal(response.status, 200);
  assert.match(await response.text(), /Mobile Workspace/);
});
