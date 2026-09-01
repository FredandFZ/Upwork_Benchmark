import featureAboutPageContent from "./features/about-page-content.mjs";
import featureBadgeAwardAccuracy from "./features/badge-award-accuracy.mjs";
import featureBadgeCatalogAndPresentation from "./features/badge-catalog-and-presentation.mjs";
import featureBaseNetworkDeployment from "./features/base-network-deployment.mjs";
import featureBookIpfsStorage from "./features/book-ipfs-storage.mjs";
import featureEbookReaderUx from "./features/ebook-reader-ux.mjs";
import featureEmailDashboardAuthentication from "./features/email-dashboard-authentication.mjs";
import featureFaqContent from "./features/faq-content.mjs";
import featureFiatBuyerWalletProvisioning from "./features/fiat-buyer-wallet-provisioning.mjs";
import featureLandingBookCoverPresentation from "./features/landing-book-cover-presentation.mjs";
import featureLandingHeroPresentation from "./features/landing-hero-presentation.mjs";
import featureLandingMechanicsCopy from "./features/landing-mechanics-copy.mjs";
import featureMauritiusGeoblock from "./features/mauritius-geoblock.mjs";
import featureMintPriceAndRevenueSplit from "./features/mint-price-and-revenue-split.mjs";
import featureMintTipping from "./features/mint-tipping.mjs";
import featureMissionPageContent from "./features/mission-page-content.mjs";
import featureNftCertificateEmail from "./features/nft-certificate-email.mjs";
import featureNftHolderBookAccess from "./features/nft-holder-book-access.mjs";
import featureNftResaleStateTransfer from "./features/nft-resale-state-transfer.mjs";
import featureNoReferralCommissionAllocation from "./features/no-referral-commission-allocation.mjs";
import featureNoReferralTicketAllocation from "./features/no-referral-ticket-allocation.mjs";
import featurePrizeClaimFlow from "./features/prize-claim-flow.mjs";
import featurePrizeWinnerNotification from "./features/prize-winner-notification.mjs";
import featureProjectBranding from "./features/project-branding.mjs";
import featurePublicApiAccess from "./features/public-api-access.mjs";
import featurePublicPrizePoolStatistics from "./features/public-prize-pool-statistics.mjs";
import featureReferralCodeIdentity from "./features/referral-code-identity.mjs";
import featureReferralCommission from "./features/referral-commission.mjs";
import featureReferralPrizeTicketIssuance from "./features/referral-prize-ticket-issuance.mjs";
import featureSecondaryRoyaltyEnforcement from "./features/secondary-royalty-enforcement.mjs";
import featureSmallBlockPrize from "./features/small-block-prize.mjs";
import featureTicketAccountingAccuracy from "./features/ticket-accounting-accuracy.mjs";
import featureTransactionalEmailDelivery from "./features/transactional-email-delivery.mjs";
import featureUnlimitedNftEbookCollection from "./features/unlimited-nft-ebook-collection.mjs";
import featureVrfWinnerSelection from "./features/vrf-winner-selection.mjs";
import featureWalletAuthentication from "./features/wallet-authentication.mjs";

const features = Object.freeze([featureAboutPageContent, featureBadgeAwardAccuracy, featureBadgeCatalogAndPresentation, featureBaseNetworkDeployment, featureBookIpfsStorage, featureEbookReaderUx, featureEmailDashboardAuthentication, featureFaqContent, featureFiatBuyerWalletProvisioning, featureLandingBookCoverPresentation, featureLandingHeroPresentation, featureLandingMechanicsCopy, featureMauritiusGeoblock, featureMintPriceAndRevenueSplit, featureMintTipping, featureMissionPageContent, featureNftCertificateEmail, featureNftHolderBookAccess, featureNftResaleStateTransfer, featureNoReferralCommissionAllocation, featureNoReferralTicketAllocation, featurePrizeClaimFlow, featurePrizeWinnerNotification, featureProjectBranding, featurePublicApiAccess, featurePublicPrizePoolStatistics, featureReferralCodeIdentity, featureReferralCommission, featureReferralPrizeTicketIssuance, featureSecondaryRoyaltyEnforcement, featureSmallBlockPrize, featureTicketAccountingAccuracy, featureTransactionalEmailDelivery, featureUnlimitedNftEbookCollection, featureVrfWinnerSelection, featureWalletAuthentication]);
const hero = {
  "headline_text": "Project Rebuild",
  "cta_text": "Mint the eBook NFT for $15",
  "layout_position": "Restore 'Project Rebuild' at the top with subtitles and the earlier overall hero layout.",
  "visual_emphasis": "Boldly emphasize key selling points such as '$500 random giveaway every 100 sales' and '$5 unlimited, instant commission'.",
  "layout_style": "Restore the earlier overall hero layout with subtitles, keeping the header uncluttered and avoiding oversized text or overlap with the dashboard button.",
  "subtitle_and_copy_treatment": "Retain supporting subtitles, but allow wording to be adapted rather than matched character for character when exact wording would make the page cluttered, repetitive, or overly salesy."
};

export const snapshot = Object.freeze({
  environment: "reconstructed-pre-event",
  projectName: "Project Rebuild",
  hero,
  features,
});

export function findFeature(key) {
  return features.find((feature) => feature.key === key) ?? null;
}
