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
