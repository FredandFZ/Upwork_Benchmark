export default Object.freeze({
  "requirement_id": "REQ_DANISH_LANGUAGE_CONFIGURATION",
  "state_id": "REQ_DANISH_LANGUAGE_CONFIGURATION_S003",
  "key": "danish-template-language-configuration",
  "title": "Danish Template Language Configuration",
  "family": null,
  "lifecycle": "ACTIVE",
  "components": [
    "WORD_TEMPLATE"
  ],
  "contexts": [
    "ALL_WORD_TEMPLATES"
  ],
  "attributes": {
    "document_content_language": "Danish",
    "default_language": "Danish"
  },
  "ambiguity": {
    "REQ_DANISH_LANGUAGE_CONFIGURATION_E003": {
      "status": "OPEN",
      "dimension": "VALUE",
      "description": "The freelancer proposes English as the default language despite the client's Danish-default requirement, requiring client confirmation.",
      "source_event_id": "REQ_DANISH_LANGUAGE_CONFIGURATION_E003"
    }
  },
  "execution": null,
  "supporting_event_ids": [
    "REQ_DANISH_LANGUAGE_CONFIGURATION_E001",
    "REQ_DANISH_LANGUAGE_CONFIGURATION_E002",
    "REQ_DANISH_LANGUAGE_CONFIGURATION_E003"
  ],
  "render_hints": {
    "documentLanguage": "da-DK"
  }
});
