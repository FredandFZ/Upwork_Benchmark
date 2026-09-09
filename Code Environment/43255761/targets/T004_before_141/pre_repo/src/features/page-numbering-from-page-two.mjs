export default Object.freeze({
  "requirement_id": "REQ_PAGE_NUMBERING_FROM_SECOND_PAGE",
  "state_id": "REQ_PAGE_NUMBERING_FROM_SECOND_PAGE_S002",
  "key": "page-numbering-from-page-two",
  "title": "Page Numbering from Page Two",
  "family": "DOCUMENT_LAYOUT",
  "lifecycle": "ACTIVE",
  "components": [
    "WORD_TEMPLATE"
  ],
  "contexts": [
    "DOCUMENT_FOOTERS"
  ],
  "attributes": {
    "first_page_footer_page_number_visible": false,
    "page_numbering_start_page": 2
  },
  "ambiguity": null,
  "execution": {
    "status": "FAILED",
    "observed_behavior": "The reviewed template displays an unwanted page number in the first-page footer instead of beginning numbering on page 2.",
    "source_event_id": "REQ_PAGE_NUMBERING_FROM_SECOND_PAGE_E002"
  },
  "supporting_event_ids": [
    "REQ_PAGE_NUMBERING_FROM_SECOND_PAGE_E001",
    "REQ_PAGE_NUMBERING_FROM_SECOND_PAGE_E002"
  ],
  "render_hints": {}
});
