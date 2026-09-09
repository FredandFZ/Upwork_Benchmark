export default Object.freeze({
  "requirement_id": "REQ_MASTER_TEMPLATE_FOUNDATION",
  "state_id": "REQ_MASTER_TEMPLATE_FOUNDATION_S003",
  "key": "shared-master-template-foundation",
  "title": "Shared Master Template Foundation",
  "family": null,
  "lifecycle": "ACTIVE",
  "components": [
    "WORD_TEMPLATE"
  ],
  "contexts": [
    "MASTER_TEMPLATE",
    "DERIVED_WORD_TEMPLATES"
  ],
  "attributes": {
    "foundation_role": "The completed Master template serves as the foundation for producing the derived Word templates."
  },
  "ambiguity": null,
  "execution": {
    "status": "VERIFIED_WORKING",
    "observed_behavior": "Client reports actively using the new master template as the basis for the other Word templates.",
    "source_event_id": "REQ_MASTER_TEMPLATE_FOUNDATION_E003"
  },
  "supporting_event_ids": [
    "REQ_MASTER_TEMPLATE_FOUNDATION_E001",
    "REQ_MASTER_TEMPLATE_FOUNDATION_E003"
  ],
  "render_hints": {}
});
