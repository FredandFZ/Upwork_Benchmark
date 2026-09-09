export default Object.freeze({
  "requirement_id": "REQ_PLACEHOLDER_CLEAR_ON_ACTIVATION",
  "state_id": "REQ_PLACEHOLDER_CLEAR_ON_ACTIVATION_S008",
  "key": "placeholder-clear-on-activation",
  "title": "Placeholder Clear on Activation",
  "family": "INTERACTIVE_FIELDS",
  "lifecycle": "ACTIVE",
  "components": [
    "WORD_TEMPLATE",
    "UI_UX"
  ],
  "contexts": [
    "INTERACTIVE_FIELDS",
    "INDSTILLING",
    "VEJLEDNING",
    "BESTYRELSESSEMINAR"
  ],
  "attributes": {
    "activation_trigger": "field click or activation",
    "placeholder_handling": "automatically remove the existing in-field text",
    "required_user_flow": "click and start typing without selecting or manually deleting the existing text"
  },
  "ambiguity": null,
  "execution": {
    "status": "FAILED",
    "observed_behavior": "Review of the subsequently updated document showed that the clear-on-click function was still missing.",
    "source_event_id": "REQ_PLACEHOLDER_CLEAR_ON_ACTIVATION_E008"
  },
  "supporting_event_ids": [
    "REQ_PLACEHOLDER_CLEAR_ON_ACTIVATION_E001",
    "REQ_PLACEHOLDER_CLEAR_ON_ACTIVATION_E004",
    "REQ_PLACEHOLDER_CLEAR_ON_ACTIVATION_E006",
    "REQ_PLACEHOLDER_CLEAR_ON_ACTIVATION_E008"
  ],
  "render_hints": {}
});
