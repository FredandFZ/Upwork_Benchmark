export default Object.freeze({
  "key": "mobile-wallet-book-access",
  "title": "Mobile Wallet Book Access",
  "family": "BOOK_DELIVERY_AND_ACCESS",
  "components": [
    "AUTH",
    "FRONTEND"
  ],
  "contexts": [
    "MOBILE_BOOK_READER",
    "MOBILE_WALLET"
  ],
  "configuration": {
    "mobile_book_access_behavior": "When using a mobile wallet, opening the gated book should provide the ownership-signature request needed to load the book."
  }
});
