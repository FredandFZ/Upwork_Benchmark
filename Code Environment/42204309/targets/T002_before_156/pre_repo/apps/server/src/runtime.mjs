import featureBadgeAwardAccuracy from "./features/badge-award-accuracy.mjs";
import featureBadgeCatalogAndPresentation from "./features/badge-catalog-and-presentation.mjs";
import featureBaseNetworkDeployment from "./features/base-network-deployment.mjs";
import featureBigBlockPrize from "./features/big-block-prize.mjs";
import featureEmailDashboardAuthentication from "./features/email-dashboard-authentication.mjs";
import featureFaqContent from "./features/faq-content.mjs";
import featureMauritiusGeoblock from "./features/mauritius-geoblock.mjs";
import featureMintPriceAndRevenueSplit from "./features/mint-price-and-revenue-split.mjs";
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
import featureTransakFiatMint from "./features/transak-fiat-mint.mjs";
import featureUnlimitedNftEbookCollection from "./features/unlimited-nft-ebook-collection.mjs";
import featureVrfWinnerSelection from "./features/vrf-winner-selection.mjs";
import featureWalletAuthentication from "./features/wallet-authentication.mjs";

const features = Object.freeze([featureBadgeAwardAccuracy, featureBadgeCatalogAndPresentation, featureBaseNetworkDeployment, featureBigBlockPrize, featureEmailDashboardAuthentication, featureFaqContent, featureMauritiusGeoblock, featureMintPriceAndRevenueSplit, featureNftResaleStateTransfer, featureNoReferralCommissionAllocation, featureNoReferralTicketAllocation, featurePrizeClaimFlow, featurePrizeWinnerNotification, featureProjectBranding, featurePublicApiAccess, featurePublicPrizePoolStatistics, featureReferralCodeIdentity, featureReferralCommission, featureReferralPrizeTicketIssuance, featureSecondaryRoyaltyEnforcement, featureSmallBlockPrize, featureTicketAccountingAccuracy, featureTransactionalEmailDelivery, featureTransakFiatMint, featureUnlimitedNftEbookCollection, featureVrfWinnerSelection, featureWalletAuthentication]);
const hero = null;

export const snapshot = Object.freeze({
  environment: "reconstructed-pre-event",
  projectName: "Project Rebuild",
  hero,
  features,
});

export function findFeature(key) {
  return features.find((feature) => feature.key === key) ?? null;
}
