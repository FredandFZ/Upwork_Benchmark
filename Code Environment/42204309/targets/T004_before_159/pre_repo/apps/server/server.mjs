import http from "node:http";
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
