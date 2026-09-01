import assert from "node:assert/strict";
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
