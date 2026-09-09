# 43255761 T005 Reconstructed Word Pre-Event Repository

This is a deterministic executable reconstruction of a Word-template state. It is not a recovered historical source repository and it does not seed any pre-event state from the final delivered DOCX files.

The repository uses the Node.js standard library only. It generates a real macro-free OOXML `.docx`, exposes behavior-level title/list/field operations, and keeps one graph-backed module per active requirement state.

## Run

```sh
npm ci --ignore-scripts
npm run check
npm run inspect
```

The generated artifact is `artifacts/reconstructed-template.docx`. The current snapshot contains 27 projected requirement states. Node.js 20 or newer is required; no network service, Microsoft Office installation, or credential is needed for build and test.
