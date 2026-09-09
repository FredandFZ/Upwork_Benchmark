export default Object.freeze({
  "key": "mobile-pricing-table-interaction",
  "title": "Mobile Pricing Table Interaction",
  "family": "PRICING_EXPERIENCE",
  "lifecycle": "ACTIVE",
  "components": [
    "FRONTEND",
    "UI_UX"
  ],
  "contexts": [
    "PRICING_PAGE",
    "MOBILE"
  ],
  "configuration": {
    "mobile_table_interaction": "show all pricing information without requiring horizontal scrolling"
  },
  "ambiguities": [
    {
      "status": "OPEN",
      "dimension": "VALUE",
      "description": "The client requested a layout without horizontal scrolling, while the agency recommended retaining horizontal scrolling or fixing the first column and requested a client decision."
    }
  ],
  "execution": null
});
