export default Object.freeze({
  "key": "nft-holder-book-access",
  "title": "NFT-Holder-Only Book Access",
  "family": "BOOK_DELIVERY_AND_ACCESS",
  "components": [
    "AUTH",
    "BACKEND",
    "FRONTEND",
    "STORAGE"
  ],
  "contexts": [
    "BOOK_READER",
    "NFT_GATED_ACCESS"
  ],
  "configuration": {
    "access_policy": "only NFT holders may access the ebook",
    "gating_provider": "Lit Protocol",
    "metadata_destination": "gated viewer page rather than the PDF directly",
    "content_protection": "encrypt the PDF and decrypt it only after NFT ownership verification",
    "ownership_verification": "automatic",
    "access_experience": "seamless open-link flow with no manual actions required"
  }
});
