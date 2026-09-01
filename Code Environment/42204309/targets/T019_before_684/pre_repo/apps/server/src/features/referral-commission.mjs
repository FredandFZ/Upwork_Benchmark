export default Object.freeze({
  "key": "referral-commission",
  "title": "Code-Used Referral Commission",
  "family": "REFERRAL_MECHANICS",
  "components": [
    "PAYMENT",
    "SMART_CONTRACT"
  ],
  "contexts": [
    "REFERRAL_MINT"
  ],
  "configuration": {
    "commission_amount": "$5",
    "payout_mode": "automatic",
    "commission_trigger": "a successful mint using a valid referral code",
    "commission_recipient": "the holder of the referral code used for the mint",
    "payout_destination": "recipient wallet",
    "payout_timing": "immediate",
    "earning_limit": "unlimited",
    "earning_expiration": "none"
  }
});
