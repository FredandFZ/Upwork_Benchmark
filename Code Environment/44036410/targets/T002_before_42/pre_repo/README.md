# 44036410 T002 Reconstructed Report Pre-Event Repository

This is a deterministic executable reconstruction of a report-layout state. It is not a recovered historical source repository and it does not seed any pre-event state from the final delivered DOCX/PDF files.

The repository uses the Node.js standard library only. It generates a real macro-free OOXML `.docx` plus a deterministic four-page PDF, exposes behavior-level dashboard/warning/footer/code operations, and keeps one graph-backed module per active requirement state.

## Run

```sh
npm ci --ignore-scripts
npm run check
npm run inspect
```

Generated artifacts are `artifacts/reconstructed-report.docx` and `artifacts/reconstructed-report.pdf`. The current snapshot contains 10 projected requirement states. Node.js 20 or newer is required; no network service, Microsoft Office installation, or credential is needed for build and test.
