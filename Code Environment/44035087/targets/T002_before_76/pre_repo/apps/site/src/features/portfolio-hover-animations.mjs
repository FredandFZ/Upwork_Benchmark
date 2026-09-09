export default Object.freeze({
  "key": "portfolio-hover-animations",
  "title": "Portfolio Hover Animations",
  "family": "GALLERY_EXPERIENCE",
  "lifecycle": "ACTIVE",
  "components": [
    "FRONTEND",
    "UI_UX"
  ],
  "contexts": [
    "HOMEPAGE_GALLERY",
    "GALLERY_ITEMS"
  ],
  "configuration": {
    "animation_effect": "hover animation",
    "mobile_hover_animations_enabled": false
  },
  "ambiguities": [
    {
      "status": "OPEN",
      "dimension": "VALUE",
      "description": "Elementor cannot configure hover effects separately for mobile and desktop, leaving unresolved whether to remove the effects everywhere or retain them everywhere."
    }
  ],
  "execution": null
});
