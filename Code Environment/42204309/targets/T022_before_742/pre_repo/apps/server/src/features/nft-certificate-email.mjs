export default Object.freeze({
  "key": "nft-certificate-email",
  "title": "NFT Certificate Email",
  "family": "BOOK_DELIVERY_AND_ACCESS",
  "components": [
    "EMAIL",
    "FRONTEND",
    "UI_UX"
  ],
  "contexts": [
    "NFT_CERTIFICATE_EMAIL"
  ],
  "configuration": {
    "delivery_condition": "after minting",
    "certificate_contents": [
      "mint number (referral code)",
      "NFT details",
      "dashboard link"
    ],
    "primary_read_button_label": "Read 'My Underdog Journey: To Own Goal' Now",
    "primary_read_action": "open the ebook in the read-only PDF.js viewer",
    "offline_download_link_label": "Download PDF for Offline Reading",
    "offline_download_link_optional": true
  }
});
