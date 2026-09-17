export default Object.freeze({
  "requirement_id": "REQ_PRIORITIZED_UPGRADE_PATH",
  "state_id": "REQ_PRIORITIZED_UPGRADE_PATH_S002",
  "key": "prioritized-security-upgrade-path",
  "title": "Prioritized Security Upgrade Path",
  "family": "REPORT_CONTENT_SECTIONS",
  "lifecycle": "ACTIVE",
  "components": [
    "DOCUMENT_TEMPLATE"
  ],
  "contexts": [
    "VEHICLE_SECURITY_REPORT",
    "RECOMMENDATIONS"
  ],
  "attributes": {
    "include_recommended_security_actions": true,
    "presentation": "clear",
    "ranking": "by priority",
    "priority_tiers": [
      "immediate actions",
      "priority upgrades",
      "secondary upgrades"
    ],
    "content_objective": "practical and action-focused"
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_PRIORITIZED_UPGRADE_PATH_E001",
    "REQ_PRIORITIZED_UPGRADE_PATH_E002"
  ],
  "render_hints": {}
});
