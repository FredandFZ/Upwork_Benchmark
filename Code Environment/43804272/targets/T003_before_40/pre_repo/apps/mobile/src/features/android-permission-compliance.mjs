export default Object.freeze({
  "key": "android-permission-compliance",
  "title": "Android Permission Compliance",
  "family": "PLATFORM_READINESS",
  "lifecycle": "ACTIVE",
  "components": [
    "ANDROID_APP"
  ],
  "contexts": [
    "ANDROID_STORE_COMPLIANCE"
  ],
  "configuration": {
    "unused_permission_policy": "do not request unused sensitive permissions",
    "read_phone_state_permission": "must be removed"
  },
  "ambiguities": [],
  "execution": null
});
