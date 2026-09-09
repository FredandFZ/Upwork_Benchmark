export default Object.freeze({
  "key": "android-os-and-api-modernization",
  "title": "Android OS and API Modernization",
  "family": "PLATFORM_READINESS",
  "lifecycle": "ACTIVE",
  "components": [
    "ANDROID_APP"
  ],
  "contexts": [
    "ANDROID_PLATFORM_COMPATIBILITY"
  ],
  "configuration": {
    "modernize_os_and_framework": true,
    "refactor_deprecated_apis": true,
    "target_android_api_level": 35,
    "update_outdated_dependencies": true
  },
  "ambiguities": [],
  "execution": {
    "status": "CLAIMED_WORKING",
    "observed_behavior": "Freelancer reports updating the measurement and splash screens to modern Android APIs and replacing the abandoned ViewFlow library with ViewPager2."
  }
});
