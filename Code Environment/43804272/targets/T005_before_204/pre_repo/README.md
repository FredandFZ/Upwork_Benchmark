# 43804272 Reconstructed Pre-Event Repository

This repository is an executable reconstruction, not a copy of the unavailable historical native source tree. It preserves the observable cross-platform capability state in a deterministic, dependency-free Node.js harness.

## Run

```sh
npm ci
npm run check
npm start
```

Open http://127.0.0.1:4380. The JSON interfaces are available at `/health`, `/api/snapshot`, `/api/diagnostics`, `/api/open-questions`, and `/api/platform/{android|ios}`.

Node.js 20 or newer is required. No network service or credential is needed.
