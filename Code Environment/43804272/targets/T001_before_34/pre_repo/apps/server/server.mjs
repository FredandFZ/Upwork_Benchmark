import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { diagnostics, featuresForPlatform, openQuestions, snapshot } from "../mobile/src/runtime.mjs";

const publicRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "mobile", "public");
const contentTypes = new Map([[".html", "text/html; charset=utf-8"], [".js", "text/javascript; charset=utf-8"], [".css", "text/css; charset=utf-8"]]);

function sendJson(response, status, value) {
  response.writeHead(status, { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" });
  response.end(JSON.stringify(value));
}

export function createServer() {
  return http.createServer((request, response) => {
    const requestUrl = new URL(request.url ?? "/", "http://localhost");
    if (request.method === "GET" && requestUrl.pathname === "/health") return sendJson(response, 200, { status: "ok" });
    if (request.method === "GET" && requestUrl.pathname === "/api/snapshot") return sendJson(response, 200, snapshot);
    if (request.method === "GET" && requestUrl.pathname === "/api/diagnostics") return sendJson(response, 200, { diagnostics: diagnostics() });
    if (request.method === "GET" && requestUrl.pathname === "/api/open-questions") return sendJson(response, 200, { questions: openQuestions() });
    if (request.method === "GET" && requestUrl.pathname.startsWith("/api/platform/")) {
      const platform = requestUrl.pathname.slice("/api/platform/".length);
      if (!new Set(["android", "ios"]).has(platform)) return sendJson(response, 404, { error: "unknown platform" });
      return sendJson(response, 200, { platform, features: featuresForPlatform(platform) });
    }
    if (request.method !== "GET" && request.method !== "HEAD") return sendJson(response, 405, { error: "method not allowed" });
    const relative = requestUrl.pathname === "/" ? "index.html" : requestUrl.pathname.replace(/^\/+/, "");
    const candidate = path.resolve(publicRoot, relative);
    if (!candidate.startsWith(publicRoot + path.sep) || !fs.existsSync(candidate) || !fs.statSync(candidate).isFile()) return sendJson(response, 404, { error: "not found" });
    response.writeHead(200, { "content-type": contentTypes.get(path.extname(candidate)) ?? "application/octet-stream" });
    if (request.method === "HEAD") return response.end();
    fs.createReadStream(candidate).pipe(response);
  });
}

export function startServer({ host = process.env.HOST ?? "127.0.0.1", port = Number(process.env.PORT ?? 4380) } = {}) {
  const server = createServer();
  server.listen(port, host, () => process.stdout.write("Mobile workspace listening on http://" + host + ":" + port + "\n"));
  return server;
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) startServer();
