# 43214420 T020 Reconstructed PCB Pre-Event Repository

This repository is a deterministic executable temporal reconstruction, not a recovered historical KiCad repository. Final delivered project assets are checksum evidence only and are never used to seed a pre-event state.

It uses the Node.js standard library to generate KiCad-compatible board and schematic fixtures plus an exact design-state artifact. Behavior-level operations expose the projected mechanical, connector, breakout, power-safety, input-interface, and manufacturing state.

## Run

```sh
npm ci --ignore-scripts
npm run check
npm run inspect
```

The snapshot contains 43 projected requirement states. Node.js 20 or newer is required. KiCad is optional for manual viewing and is not required for deterministic build or validation.
