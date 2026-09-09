export default Object.freeze({
  "requirement_id": "REQ_TAB_DRIVEN_LIST_HIERARCHY",
  "state_id": "REQ_TAB_DRIVEN_LIST_HIERARCHY_S003",
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
  "ambiguity": {
    "REQ_TAB_DRIVEN_LIST_HIERARCHY_E003": {
      "status": "OPEN",
      "dimension": "VALUE",
      "description": "The client requires users to create list sub-levels naturally with Tab, but the freelancer attributes the observed breakage to not selecting styles through the style ribbon, leaving the required Tab-only workflow unresolved.",
      "source_event_id": "REQ_TAB_DRIVEN_LIST_HIERARCHY_E003"
    }
  },
  "execution": {
    "status": "FAILED",
    "observed_behavior": "The client reports that the list breaks after three bullets.",
    "source_event_id": "REQ_TAB_DRIVEN_LIST_HIERARCHY_E002"
  },
  "supporting_event_ids": [
    "REQ_TAB_DRIVEN_LIST_HIERARCHY_E001",
    "REQ_TAB_DRIVEN_LIST_HIERARCHY_E002",
    "REQ_TAB_DRIVEN_LIST_HIERARCHY_E003"
  ],
  "render_hints": {}
});
