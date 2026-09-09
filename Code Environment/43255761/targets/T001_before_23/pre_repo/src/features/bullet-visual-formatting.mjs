export default Object.freeze({
  "requirement_id": "REQ_BULLET_VISUAL_FORMATTING",
  "state_id": "REQ_BULLET_VISUAL_FORMATTING_S001",
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
    "scaling_behavior": "follows font size naturally"
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_BULLET_VISUAL_FORMATTING_E001"
  ],
  "render_hints": {
    "bulletApproved": false
  }
});
