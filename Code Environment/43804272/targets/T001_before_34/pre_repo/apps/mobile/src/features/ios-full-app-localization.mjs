export default Object.freeze({
  "key": "ios-full-app-localization",
  "title": "iOS Full-App Localization",
  "family": "APPLICATION_LOCALIZATION",
  "lifecycle": "ACTIVE",
  "components": [
    "IOS_APP"
  ],
  "contexts": [
    "APPLICATION_LOCALIZATION"
  ],
  "configuration": {
    "localization_scale": "large-scale"
  },
  "ambiguities": [
    {
      "status": "OPEN",
      "dimension": "SCOPE",
      "description": "It was not yet confirmed whether localization should cover the entire iOS application or only its App Store listing."
    }
  ],
  "execution": {
    "status": "FAILED",
    "observed_behavior": "The iOS localization system lacks translation files and displays English regardless of the phone's selected language."
  }
});
