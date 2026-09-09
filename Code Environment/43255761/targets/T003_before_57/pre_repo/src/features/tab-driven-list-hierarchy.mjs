export default Object.freeze({
  "requirement_id": "REQ_TAB_DRIVEN_LIST_HIERARCHY",
  "state_id": "REQ_TAB_DRIVEN_LIST_HIERARCHY_S001",
  "key": "tab-driven-list-hierarchy",
  "title": "Tab-Driven List Hierarchy",
  "family": "LIST_BEHAVIOR",
  "lifecycle": "ACTIVE",
  "components": [
    "WORD_TEMPLATE"
  ],
  "contexts": [
    "BULLET_LISTS",
    "NUMBERED_LISTS",
    "ALL_WORD_TEMPLATES"
  ],
  "attributes": {
    "level_transition_method": "Tab key",
    "applicable_lists": "every applicable list style",
    "hierarchy_structure": "orderly and clearly structured",
    "nested_level_alignment": "consistent across the document"
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_TAB_DRIVEN_LIST_HIERARCHY_E001"
  ],
  "render_hints": {}
});
