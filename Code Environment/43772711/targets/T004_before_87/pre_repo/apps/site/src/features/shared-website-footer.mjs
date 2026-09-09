export default Object.freeze({
  "key": "shared-website-footer",
  "title": "Shared Website Footer",
  "family": "WEBSITE_NAVIGATION_AND_CHROME",
  "lifecycle": "OBSERVED",
  "components": [],
  "contexts": [
    "WEBSITE_FOOTER",
    "FOLLOW_ON_WEB_PAGES",
    "SITE_NAVIGATION"
  ],
  "configuration": {
    "shared_across_webpages": "Shared by default, but optional on the Sign In page and Account Provisioning wizard.",
    "site_navigation_location": "footer instead of header",
    "branding_content": "Actia AI or logo",
    "location_content": [
      "Emeryville",
      "California, USA"
    ],
    "contact_channels": [
      "email",
      "phone"
    ],
    "menu_links": [
      "Home",
      "Contact Us",
      "Support",
      "Cookie Notice",
      "Privacy Policy",
      "Terms of Use",
      "Legal"
    ],
    "social_links": [
      "LinkedIn",
      "X"
    ],
    "copyright_notice": "Copyright (c) 2026 Actia LLC. All rights reserved",
    "content_layout": {
      "company_details": "left block",
      "menu_links": "right block",
      "social_and_copyright": "bottom center"
    },
    "background_treatment": "solid dark gray",
    "informational_page_inclusion": {
      "sign_in_page": "optional",
      "account_provisioning_wizard": "optional"
    }
  },
  "ambiguities": [
    {
      "status": "OPEN",
      "dimension": "VALUE",
      "description": "The freelancer substituted dark purple for the client-confirmed dark-gray footer background and requested a decision."
    }
  ],
  "execution": null
});
