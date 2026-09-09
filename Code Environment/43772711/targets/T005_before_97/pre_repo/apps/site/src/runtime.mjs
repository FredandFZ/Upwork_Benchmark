import featureAccountProvisioningWizardStyling from "./features/account-provisioning-wizard-styling.mjs";
import featureAgentSolutionDescriptionPage from "./features/agent-solution-description-page.mjs";
import featureAssociatedPageHeaderMenu from "./features/associated-page-header-menu.mjs";
import featureAwsCognitoSignInPageStyling from "./features/aws-cognito-sign-in-page-styling.mjs";
import featureClockwiseCycleDiagram from "./features/clockwise-cycle-diagram.mjs";
import featureConsoleButtonVisualStyle from "./features/console-button-visual-style.mjs";
import featureConsoleNavigationPanelStructure from "./features/console-navigation-panel-structure.mjs";
import featureConsoleShellVisualDesign from "./features/console-shell-visual-design.mjs";
import featureCrossPageResponsiveDesignRules from "./features/cross-page-responsive-design-rules.mjs";
import featureCustomerAndStaffCommunicationDiagram from "./features/customer-and-staff-communication-diagram.mjs";
import featureLandingPageContentDistribution from "./features/landing-page-content-distribution.mjs";
import featureLandingPageHowItWorksSection from "./features/landing-page-how-it-works-section.mjs";
import featureLandingPageSignUpCallToAction from "./features/landing-page-sign-up-call-to-action.mjs";
import featureLandingPageVisualSystem from "./features/landing-page-visual-system.mjs";
import featureLegalDocumentAccess from "./features/legal-document-access.mjs";
import featurePlatformSolutionDescriptionPage from "./features/platform-solution-description-page.mjs";
import featureProvisioningWizardRoughCodeDeliverable from "./features/provisioning-wizard-rough-code-deliverable.mjs";
import featureResponsiveLandingPageLayout from "./features/responsive-landing-page-layout.mjs";
import featureSharedVisualFoundationForWebsitePages from "./features/shared-visual-foundation-for-website-pages.mjs";
import featureSharedWebsiteFooter from "./features/shared-website-footer.mjs";
import featureSignInPageRoughCodeDeliverable from "./features/sign-in-page-rough-code-deliverable.mjs";
import featureWebDesignSystemSpecification from "./features/web-design-system-specification.mjs";
import featureWebsiteImplementationStack from "./features/website-implementation-stack.mjs";

const features = Object.freeze([featureAccountProvisioningWizardStyling, featureAgentSolutionDescriptionPage, featureAssociatedPageHeaderMenu, featureAwsCognitoSignInPageStyling, featureClockwiseCycleDiagram, featureConsoleButtonVisualStyle, featureConsoleNavigationPanelStructure, featureConsoleShellVisualDesign, featureCrossPageResponsiveDesignRules, featureCustomerAndStaffCommunicationDiagram, featureLandingPageContentDistribution, featureLandingPageHowItWorksSection, featureLandingPageSignUpCallToAction, featureLandingPageVisualSystem, featureLegalDocumentAccess, featurePlatformSolutionDescriptionPage, featureProvisioningWizardRoughCodeDeliverable, featureResponsiveLandingPageLayout, featureSharedVisualFoundationForWebsitePages, featureSharedWebsiteFooter, featureSignInPageRoughCodeDeliverable, featureWebDesignSystemSpecification, featureWebsiteImplementationStack]);

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
