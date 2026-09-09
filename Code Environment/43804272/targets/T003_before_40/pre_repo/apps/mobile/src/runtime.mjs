import featureAndroidDownloadSizeOptimization from "./features/android-download-size-optimization.mjs";
import featureAndroidFullAppLocalization from "./features/android-full-app-localization.mjs";
import featureAndroidOsAndApiModernization from "./features/android-os-and-api-modernization.mjs";
import featureAndroidPermissionCompliance from "./features/android-permission-compliance.mjs";
import featureAndroidRightToLeftLayoutSupport from "./features/android-right-to-left-layout-support.mjs";
import featureChineseYoukuVideoIntegration from "./features/chinese-youku-video-integration.mjs";
import featureIosAppThinning from "./features/ios-app-thinning.mjs";
import featureIosDownloadSizeOptimization from "./features/ios-download-size-optimization.mjs";
import featureIosFullAppLocalization from "./features/ios-full-app-localization.mjs";
import featureIosOsAndApiModernization from "./features/ios-os-and-api-modernization.mjs";
import featureIosPrivacyManifest from "./features/ios-privacy-manifest.mjs";
import featureIosRightToLeftLayoutSupport from "./features/ios-right-to-left-layout-support.mjs";

const features = Object.freeze([featureAndroidDownloadSizeOptimization, featureAndroidFullAppLocalization, featureAndroidOsAndApiModernization, featureAndroidPermissionCompliance, featureAndroidRightToLeftLayoutSupport, featureChineseYoukuVideoIntegration, featureIosAppThinning, featureIosDownloadSizeOptimization, featureIosFullAppLocalization, featureIosOsAndApiModernization, featureIosPrivacyManifest, featureIosRightToLeftLayoutSupport]);

export const snapshot = Object.freeze({
  environment: "reconstructed-pre-event",
  product: "Cross-platform mobile workspace",
  features,
});

export function featuresForPlatform(platform) {
  const component = platform === "android" ? "ANDROID_APP" : platform === "ios" ? "IOS_APP" : null;
  if (!component) return [];
  return features.filter((feature) => feature.components.includes(component) || feature.components.includes("UI_UX") || feature.components.includes("BUILD_PIPELINE"));
}

export function diagnostics() {
  return features
    .filter((feature) => feature.execution)
    .map((feature) => ({ key: feature.key, ...feature.execution }));
}

export function openQuestions() {
  return features.flatMap((feature) => feature.ambiguities.map((ambiguity) => ({ key: feature.key, ...ambiguity })));
}
