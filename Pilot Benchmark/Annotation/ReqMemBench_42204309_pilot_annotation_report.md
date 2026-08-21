# ReqMemBench Pilot Annotation — Project 42204309

- Sessions: **6**
- Requirement lifecycles: **6**
- State-change events: **38**

## Session segmentation

| Session | Date | Contract milestone | Role |
|---|---|---|---|
| S1 | 2025-11-18–2025-11-25 | M1 | Smart-contract MVP and testnet validation |
| S2 | 2025-11-26–2025-12-02 | M2 | Backend/frontend integration |
| S3 | 2025-12-03–2025-12-08 | M2 | Requirement refinement |
| S4 | 2025-12-12–2025-12-31 | M2 | Simplification and mainnet preparation |
| S5 | 2026-01-01–2026-01-05 | M2 | Production QA and ETH payment addition |
| S6 | 2026-01-06–2026-01-08 | M2 | Final QA and launch |

## Requirement lifecycle summary

| Requirement | RQs | Key lifecycle | Gold state at final target |
|---|---|---|---|
| `REQ_PRIZE_MECHANICS` Prize-pool / Big Block mechanics | RQ1, RQ2, RQ3, RQ5 | INTRODUCE → MODIFY → MODIFY → IMPLEMENTATION_CLAIM → MODIFY → REMOVE_AND_MODIFY → CLARIFY | big_block=REMOVED; small_prize=$500; frequency=every 100 sales; ticket_rule=1 ticket per referral; primary_split=$5 referral / $5 small prize pool / $5 founder |
| `REQ_FIAT_ONRAMP` Fiat on-ramp provider and launch availability | RQ1, RQ3, RQ4, RQ5 | INTRODUCE → MODIFY → VALIDITY_DISCOVERY → PROPOSE → CONFIRM → DEFER → PRIORITY_UPDATE → LAUNCH_DECISION | launch_payment_mode=CRYPTO_ONLY; fiat_provider=TRANSAK; transak_status=DEFERRED / COMING_SOON |
| `REQ_MAURITIUS_GEOBLOCK` Mauritius geoblock scope | RQ1, RQ2, RQ4 | INTRODUCE → CLARIFICATION_REQUEST → SCOPE_CLARIFY | landing_page_access=BLOCK_MAURITIUS; business_jurisdiction=MAURITIUS_REMAINS_RELEVANT; stripe_eligibility=NOT_RESOLVED_BY_GEOBLOCK |
| `REQ_AAVE_INTEGRATION` Aave yield integration | RQ1, RQ3, RQ5 | ACTIVE_REFERENCE → VALIDITY_WARNING → REMOVAL_REQUEST → REMOVAL_CONFIRMATION | aave=REMOVED |
| `REQ_NO_REFERRAL_RANDOM_REWARD` No-referral random commission and ticket | RQ1, RQ2, RQ3, RQ4, RQ5 | INTRODUCE → CLARIFY → RUNTIME_FAILURE_DISCOVERY → EDGE_CASE_EXPLANATION → RUNTIME_FAILURE_DISCOVERY → PARTIAL_RECONSIDERATION → ROOT_CAUSE → FINAL_CLARIFY → RUNTIME_VERIFICATION | normal_no_referral=random existing NFT gets +1 ticket and +$5 commission; accounting=must appear in leaderboard/NFT state; first_mint_exception=no prior NFT; accepted one-off exception |
| `REQ_ETH_PAYMENT` ETH payment option for minting | RQ3, RQ4, RQ5 | CURRENT_STATE → CLARIFICATION_REQUEST → NEW_REQUIREMENT → IMPLEMENTATION_COMMIT → RUNTIME_FAILURE_DISCOVERY → IMPLEMENTATION_CLAIM → RUNTIME_VERIFICATION | payment_options=['USDC', 'ETH']; eth_status=LIVE_AND_RUNTIME_VERIFIED |

## RQ-oriented gold examples

| RQ | Gold example from this project | Expected behavior |
|---|---|---|
| RQ1 Selection | Final prize-state task | Retrieve Dec-12/Dec-17 prize updates; older Big Block history is relevant provenance but must not govern current code; ignore unrelated email/geoblock/UI history. |
| RQ2 Scope | Mauritius geoblock | Apply to landing-page access only; do not generalize it to business jurisdiction/payment-provider eligibility. |
| RQ3 Validity | Prize + fiat + Aave | Resolve Big Block to REMOVED; Transak to DEFERRED/COMING_SOON at launch; Aave to REMOVED. |
| RQ4 Memory-or-Clarify | ETH request and geoblock/Stripe question | Clarify before inventing ETH support or transferring geoblock scope; USE current explicit state once clarified. |
| RQ5 Traceability | No-referral random reward + ETH payment | Track requirement → implementation → runtime behavior. No-referral failed due to missing follow-up/backend orchestration before later runtime recovery; ETH ended with client-verified success. |

## Evidence strength

- **Code-level:** Milestone-1 Solidity source/tests verify the early prize split/ticket/random-referral implementation.
- **Runtime-level:** Jan 1–7 client production tests provide strong evidence for ETH and no-referral behavior.
- **Deliverable-level:** Final launch PDF verifies final product claims such as one $500 prize every 100 sales and Transak as coming soon.

## Important ambiguity preserved

The no-referral **ticket** rule becomes temporarily ambiguous on 2026-01-06 (client says ticket generation could go either way) and is explicitly re-established on 2026-01-07. This is intentionally kept as an ambiguity/clarification case rather than flattened into one timeless requirement.
