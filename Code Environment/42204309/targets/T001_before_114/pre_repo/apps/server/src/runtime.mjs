import featureBadgeCatalogAndPresentation from "./features/badge-catalog-and-presentation.mjs";
import featureBigBlockPrize from "./features/big-block-prize.mjs";
import featureEmailDashboardAuthentication from "./features/email-dashboard-authentication.mjs";
import featureMauritiusGeoblock from "./features/mauritius-geoblock.mjs";
import featureNoReferralTicketAllocation from "./features/no-referral-ticket-allocation.mjs";
import featurePrizeClaimFlow from "./features/prize-claim-flow.mjs";
import featureProjectBranding from "./features/project-branding.mjs";
import featurePublicApiAccess from "./features/public-api-access.mjs";
import featurePublicPrizePoolStatistics from "./features/public-prize-pool-statistics.mjs";
import featureReferralCommission from "./features/referral-commission.mjs";
import featureReferralPrizeTicketIssuance from "./features/referral-prize-ticket-issuance.mjs";
import featureSecondaryRoyaltyEnforcement from "./features/secondary-royalty-enforcement.mjs";
import featureSmallBlockPrize from "./features/small-block-prize.mjs";
import featureTicketAccountingAccuracy from "./features/ticket-accounting-accuracy.mjs";
import featureTransactionalEmailDelivery from "./features/transactional-email-delivery.mjs";
import featureTransakFiatMint from "./features/transak-fiat-mint.mjs";
import featureVrfWinnerSelection from "./features/vrf-winner-selection.mjs";
import featureWalletAuthentication from "./features/wallet-authentication.mjs";

const features = Object.freeze([featureBadgeCatalogAndPresentation, featureBigBlockPrize, featureEmailDashboardAuthentication, featureMauritiusGeoblock, featureNoReferralTicketAllocation, featurePrizeClaimFlow, featureProjectBranding, featurePublicApiAccess, featurePublicPrizePoolStatistics, featureReferralCommission, featureReferralPrizeTicketIssuance, featureSecondaryRoyaltyEnforcement, featureSmallBlockPrize, featureTicketAccountingAccuracy, featureTransactionalEmailDelivery, featureTransakFiatMint, featureVrfWinnerSelection, featureWalletAuthentication]);
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
