import featureClientSuppliedImagesForSiteSections from "./features/client-supplied-images-for-site-sections.mjs";
import featureGalleryCategoryFilters from "./features/gallery-category-filters.mjs";
import featureGalleryPortfolioImageContent from "./features/gallery-portfolio-image-content.mjs";
import featureGalleryPortfolioVideo from "./features/gallery-portfolio-video.mjs";
import featureHomepageHeroPresentation from "./features/homepage-hero-presentation.mjs";
import featureHomepagePageLinkButtons from "./features/homepage-page-link-buttons.mjs";
import featureHomepagePortfolioTileLinks from "./features/homepage-portfolio-tile-links.mjs";
import featureHomepagePortfolioVideo from "./features/homepage-portfolio-video.mjs";
import featureImageFocusedSitePresentation from "./features/image-focused-site-presentation.mjs";
import featureIndividualServicePricingTransparency from "./features/individual-service-pricing-transparency.mjs";
import featureInteractiveGalleryBrowsing from "./features/interactive-gallery-browsing.mjs";
import featureMobilePricingTableInteraction from "./features/mobile-pricing-table-interaction.mjs";
import featureOneTimePricingModel from "./features/one-time-pricing-model.mjs";
import featurePackageAndSquareFootagePricingDisplay from "./features/package-and-square-footage-pricing-display.mjs";
import featurePortfolioHoverAnimations from "./features/portfolio-hover-animations.mjs";
import featureResponsiveSiteLayout from "./features/responsive-site-layout.mjs";
import featureServiceSpecificImagery from "./features/service-specific-imagery.mjs";

const features = Object.freeze([featureClientSuppliedImagesForSiteSections, featureGalleryCategoryFilters, featureGalleryPortfolioImageContent, featureGalleryPortfolioVideo, featureHomepageHeroPresentation, featureHomepagePageLinkButtons, featureHomepagePortfolioTileLinks, featureHomepagePortfolioVideo, featureImageFocusedSitePresentation, featureIndividualServicePricingTransparency, featureInteractiveGalleryBrowsing, featureMobilePricingTableInteraction, featureOneTimePricingModel, featurePackageAndSquareFootagePricingDisplay, featurePortfolioHoverAnimations, featureResponsiveSiteLayout, featureServiceSpecificImagery]);

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
