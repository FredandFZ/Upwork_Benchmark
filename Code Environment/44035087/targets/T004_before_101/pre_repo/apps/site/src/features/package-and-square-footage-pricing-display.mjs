export default Object.freeze({
  "key": "package-and-square-footage-pricing-display",
  "title": "Package and Square-Footage Pricing Display",
  "family": "PRICING_EXPERIENCE",
  "lifecycle": "ACTIVE",
  "components": [
    "FRONTEND",
    "UI_UX"
  ],
  "contexts": [
    "PACKAGE_PRICING"
  ],
  "configuration": {
    "package_count": 4,
    "package_presentation": "four pricing boxes",
    "price_display_mode": "prices vary by square-footage range",
    "prices_per_package": 4,
    "square_footage_ranges": [
      "under 1000 sqft",
      "1001-2000 sqft",
      "2001-3000 sqft",
      "3000+ sqft"
    ],
    "basic_package_prices_by_square_footage": {
      "under_1000_sqft_usd": 250,
      "1001_2000_sqft_usd": 415,
      "2001_3000_sqft_usd": 580,
      "3000_plus_sqft_usd": 745
    }
  },
  "ambiguities": [],
  "execution": {
    "status": "CLAIMED_WORKING",
    "observed_behavior": "The agency reports revising the Pricing page to reflect the requested package and square-footage pricing feedback."
  }
});
