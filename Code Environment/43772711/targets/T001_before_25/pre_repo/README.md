# 43772711 Reconstructed Website Pre-Event Repository

This repository is an executable reconstruction, not a copy of the unavailable historical HTML/Tailwind website or separate React console source trees. It preserves the observable design and responsive-site capability state in a deterministic, dependency-free Node.js harness.

## Run

```sh
npm ci
npm run check
npm start
```

Open http://127.0.0.1:4377. The JSON interfaces are available at `/health`, `/api/snapshot`, `/api/diagnostics`, `/api/open-questions`, and `/api/viewport/{desktop|tablet|mobile}`.

Node.js 20 or newer is required. No network service or credential is needed.
