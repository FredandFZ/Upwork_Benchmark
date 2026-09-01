export default Object.freeze({
  "key": "wallet-authentication",
  "title": "Wallet Authentication",
  "family": "AUTHENTICATION_AND_ACCESS",
  "components": [
    "AUTH",
    "BACKEND",
    "FRONTEND"
  ],
  "contexts": [
    "CRYPTO_USER",
    "WALLET_AUTH"
  ],
  "configuration": {
    "authentication_method": "Sign-In with Ethereum (SIWE)",
    "crypto_flow_usage": [
      "minting",
      "transfers"
    ]
  }
});
