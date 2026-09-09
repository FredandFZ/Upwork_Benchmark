export default Object.freeze({
  "key": "account-provisioning-wizard-styling",
  "title": "Account Provisioning Wizard Styling",
  "family": "ACCESS_AND_PROVISIONING_UI",
  "lifecycle": "ACTIVE",
  "components": [
    "FRONTEND",
    "UI_UX"
  ],
  "contexts": [
    "ACCOUNT_PROVISIONING",
    "PROVISIONING_WIZARD"
  ],
  "configuration": {
    "required_visual_specification": [
      "type scale",
      "active-node accent",
      "canvas surface color",
      "muted text color",
      "soft hairline",
      "node glow",
      "horizontal page margins",
      "wizard panel width",
      "wizard node size",
      "portrait and landscape gaps",
      "Back and Next hover and active states",
      "final chevron asset"
    ],
    "supported_orientations": [
      "portrait",
      "landscape"
    ]
  },
  "ambiguities": [
    {
      "status": "OPEN",
      "dimension": "VALUE",
      "description": "The active-node accent remains undecided between Signal purple and Pulse green, and the listed color and layout values still require confirmation or substitution."
    }
  ],
  "execution": null
});
