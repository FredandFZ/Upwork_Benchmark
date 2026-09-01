export default Object.freeze({
  "key": "contract-upgrade-data-continuity",
  "title": "Contract Upgrade Data Continuity",
  "family": "CURRENT_CAPABILITY",
  "components": [
    "BACKEND",
    "INFRASTRUCTURE",
    "SMART_CONTRACT"
  ],
  "contexts": [
    "CONTRACT_MIGRATION"
  ],
  "configuration": {
    "migration_strategy": "replace the active contract with a fresh contract state",
    "nft_numbering_policy": "restart NFT numbering at #1",
    "superseded_contract_policy": "leave the prior NFT contract on-chain but exclude it from project systems",
    "data_continuity_policy": "do not migrate NFT copies from the superseded contract"
  }
});
