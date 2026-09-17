export default Object.freeze({
  "requirement_id": "REQ_DESIGN_ASSET_HANDOFF",
  "state_id": "REQ_DESIGN_ASSET_HANDOFF_S001",
  "key": "design-asset-handoff",
  "title": "Design Asset Handoff",
  "family": "DELIVERABLE_PACKAGE",
  "lifecycle": "ACTIVE",
  "components": [
    "DOCUMENT_DESIGN"
  ],
  "contexts": [
    "DESIGN_ASSET_HANDOFF"
  ],
  "attributes": {
    "included_assets": [
      "fonts",
      "icons",
      "design_assets_required_for_future_editing"
    ],
    "handoff_purpose": "enable future report updates"
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_DESIGN_ASSET_HANDOFF_E001"
  ],
  "render_hints": {}
});
