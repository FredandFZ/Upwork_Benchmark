export default Object.freeze({
  "requirement_id": "REQ_BULLET_VISUAL_FORMATTING",
  "state_id": "REQ_BULLET_VISUAL_FORMATTING_S005",
  "key": "bullet-visual-formatting",
  "title": "Bullet Visual Formatting",
  "family": "LIST_BEHAVIOR",
  "lifecycle": "ACTIVE",
  "components": [
    "WORD_TEMPLATE",
    "UI_UX"
  ],
  "contexts": [
    "BULLET_LISTS",
    "ALL_WORD_TEMPLATES"
  ],
  "attributes": {
    "bullet_dimensions": "proportional to text size",
    "visual_balance": "visually balanced",
    "vertical_alignment": "centered against the text",
    "scaling_behavior": "follows font size naturally",
    "approved_appearance": "match the customer-provided bullet list design",
    "level_4_variant": "green bullet"
  },
  "ambiguity": null,
  "execution": {
    "status": "FAILED",
    "observed_behavior": "The client reports that the bullet sizes and spacing in the Master template still look wrong on their screen.",
    "source_event_id": "REQ_BULLET_VISUAL_FORMATTING_E005"
  },
  "supporting_event_ids": [
    "REQ_BULLET_VISUAL_FORMATTING_E001",
    "REQ_BULLET_VISUAL_FORMATTING_E002",
    "REQ_BULLET_VISUAL_FORMATTING_E003",
    "REQ_BULLET_VISUAL_FORMATTING_E005"
  ],
  "render_hints": {
    "bulletApproved": true
  }
});
