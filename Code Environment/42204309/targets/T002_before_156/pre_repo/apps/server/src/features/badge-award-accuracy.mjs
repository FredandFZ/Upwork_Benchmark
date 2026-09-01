export default Object.freeze({
  "key": "badge-award-accuracy",
  "title": "Badge Award Accuracy",
  "family": "ACHIEVEMENT_SYSTEM",
  "components": [
    "SMART_CONTRACT"
  ],
  "contexts": [
    "ACHIEVEMENTS",
    "BADGES"
  ],
  "configuration": {
    "first_referral_badge_trigger": "first referral",
    "award_condition": "reach a referral milestone",
    "documented_referral_milestones": [
      2,
      10,
      50,
      "100+"
    ],
    "award_recording": "add the badge to the NFT on-chain"
  }
});
