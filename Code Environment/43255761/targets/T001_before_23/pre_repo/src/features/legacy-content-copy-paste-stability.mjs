export default Object.freeze({
  "requirement_id": "REQ_LEGACY_COPY_PASTE_STABILITY",
  "state_id": "REQ_LEGACY_COPY_PASTE_STABILITY_S002",
  "key": "legacy-content-copy-paste-stability",
  "title": "Legacy Content Copy-Paste Stability",
  "family": null,
  "lifecycle": "ACTIVE",
  "components": [
    "WORD_TEMPLATE"
  ],
  "contexts": [
    "LEGACY_CONTENT_MIGRATION",
    "ALL_WORD_TEMPLATES"
  ],
  "attributes": {
    "legacy_source_templates": [
      "Old_v1.docx",
      "Old_v2.docx"
    ],
    "migration_target": "new templates, including V14",
    "expected_copy_paste_behavior": "Layout remains stable and style behavior remains predictable when content is transferred from legacy PBU templates.",
    "stability_standard": "as stable and technically robust as possible"
  },
  "ambiguity": null,
  "execution": {
    "status": "FAILED",
    "observed_behavior": "Users encounter significant formatting and style instability when transferring content from older templates into the new templates.",
    "source_event_id": "REQ_LEGACY_COPY_PASTE_STABILITY_E002"
  },
  "supporting_event_ids": [
    "REQ_LEGACY_COPY_PASTE_STABILITY_E001",
    "REQ_LEGACY_COPY_PASTE_STABILITY_E002"
  ],
  "render_hints": {}
});
