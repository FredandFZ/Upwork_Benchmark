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
    "DASHBOARD_ACCESS",
    "FIAT_BUYER",
    "WALLET_AUTH"
  ],
  "configuration": {
    "authentication_method": "Sign-In with Ethereum (SIWE)",
    "crypto_flow_usage": [
      "minting",
      "transfers"
    ],
    "transak_wallet_dashboard_access": "Allow dashboard sign-in through SIWE using the wallet created by Transak"
  }
});
