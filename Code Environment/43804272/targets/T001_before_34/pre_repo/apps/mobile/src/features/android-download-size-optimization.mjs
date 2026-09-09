export default Object.freeze({
  "key": "android-download-size-optimization",
  "title": "Android Download Size Optimization",
  "family": "APP_SIZE_AND_PACKAGING",
  "lifecycle": "ACTIVE",
  "components": [
    "ANDROID_APP"
  ],
  "contexts": [
    "ANDROID_DISTRIBUTION"
  ],
  "configuration": {
    "optimization_goal": "Keep the Android application lightweight through app size optimization."
  },
  "ambiguities": [],
  "execution": {
    "status": "FAILED",
    "observed_behavior": "Source review measured the Android application at 89 MB and found that code shrinking and image optimization were not being used."
  }
});
