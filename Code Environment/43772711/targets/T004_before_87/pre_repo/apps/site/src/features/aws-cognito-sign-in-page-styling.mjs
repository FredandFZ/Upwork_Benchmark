export default Object.freeze({
  "key": "aws-cognito-sign-in-page-styling",
  "title": "AWS Cognito Sign-In Page Styling",
  "family": "ACCESS_AND_PROVISIONING_UI",
  "lifecycle": "ACTIVE",
  "components": [
    "AUTH",
    "FRONTEND",
    "UI_UX"
  ],
  "contexts": [
    "SIGN_IN_PAGE",
    "AWS_COGNITO"
  ],
  "configuration": {
    "custom_branding_required": true,
    "brand": "Actia",
    "page_purpose": "informational_non_marketing",
    "required_visual_elements": [
      "background",
      "header_logo"
    ],
    "background_style_basis": "landing_page_background",
    "footer_inclusion": "optional",
    "page_generation": "AWS Cognito-generated",
    "customization_boundary": "Customize the visual styling while retaining the Cognito-generated authentication page."
  },
  "ambiguities": [],
  "execution": {
    "status": "CLAIMED_WORKING",
    "observed_behavior": "Freelancer reports developing a design for the Sign In page."
  }
});
