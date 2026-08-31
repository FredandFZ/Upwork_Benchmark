# Cenv boundary record

## Classification

- Baseline: `C_env`
- Reconstruction type: simulated and reduced
- Project identifier: `42204309`
- Scope: smart-contract repository
- Historical-original claim: no

## Included

- Compiler and framework configuration
- A semantically empty contract used as a compilation and deployment probe
- A dependency-free smoke test
- A neutral deployment entry point
- Local and container validation commands

## Excluded by construction

- Domain vocabulary and domain data
- Product behavior and business invariants
- Product-specific interfaces, events, errors, and storage
- External application and protocol integrations
- Credentials, deployment addresses, transaction history, and generated artifacts

## Acceptance rule

The baseline is acceptable only if it compiles with the declared compiler, the smoke test passes, the deployment
entry point can execute in simulation, and no later product behavior can be reached from the code in this archive.
