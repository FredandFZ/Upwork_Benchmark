import featureConsoleShellVisualDesign from "./features/console-shell-visual-design.mjs";
import featureLandingPageContentDistribution from "./features/landing-page-content-distribution.mjs";
import featureLandingPageHowItWorksSection from "./features/landing-page-how-it-works-section.mjs";
import featureLandingPageSignUpCallToAction from "./features/landing-page-sign-up-call-to-action.mjs";
import featureLandingPageVisualSystem from "./features/landing-page-visual-system.mjs";
import featureSharedWebsiteFooter from "./features/shared-website-footer.mjs";
import featureWebsiteImplementationStack from "./features/website-implementation-stack.mjs";

const features = Object.freeze([featureConsoleShellVisualDesign, featureLandingPageContentDistribution, featureLandingPageHowItWorksSection, featureLandingPageSignUpCallToAction, featureLandingPageVisualSystem, featureSharedWebsiteFooter, featureWebsiteImplementationStack]);

export const snapshot = Object.freeze({
  environment: "reconstructed-pre-event",
  product: "Website workspace",
  features,
});

export function featuresForViewport(viewport) {
  if (!new Set(["desktop", "tablet", "mobile"]).has(viewport)) return [];
  return features;
}

export function diagnostics() {
  return features
    .filter((feature) => feature.execution)
    .map((feature) => ({ key: feature.key, ...feature.execution }));
}

export function openQuestions() {
  return features.flatMap((feature) => feature.ambiguities.map((ambiguity) => ({ key: feature.key, ...ambiguity })));
}
