export default Object.freeze({
  "key": "ebook-reader-ux",
  "title": "Ebook Reader UX",
  "family": "BOOK_DELIVERY_AND_ACCESS",
  "components": [
    "FRONTEND",
    "UI_UX"
  ],
  "contexts": [
    "BOOK_READER"
  ],
  "configuration": {
    "default_view_mode": "read-only",
    "viewer_technology": "PDF.js",
    "viewer_entry_points": [
      "dashboard",
      "email link"
    ],
    "offline_pdf_download": {
      "availability": "optional",
      "link_label": "Download PDF for Offline Reading"
    }
  }
});
