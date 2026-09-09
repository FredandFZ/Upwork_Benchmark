export default Object.freeze({
  "requirement_id": "REQ_PAGE_FIT_SPACING",
  "state_id": "REQ_PAGE_FIT_SPACING_S002",
  "key": "page-fit-spacing",
  "title": "Page-Fit Spacing",
  "family": "DOCUMENT_LAYOUT",
  "lifecycle": "ACTIVE",
  "components": [],
  "contexts": [],
  "attributes": {
    "page_fit_target": "all content fits on one page",
    "spacing_adjustment": "reduce spacing as needed"
  },
  "ambiguity": null,
  "execution": {
    "status": "FAILED",
    "observed_behavior": "After copying content from the old version, the client reports that the current spacing does not allow everything to fit on one page.",
    "source_event_id": "REQ_PAGE_FIT_SPACING_E002"
  },
  "supporting_event_ids": [
    "REQ_PAGE_FIT_SPACING_E001",
    "REQ_PAGE_FIT_SPACING_E002"
  ],
  "render_hints": {}
});
