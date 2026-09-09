export default Object.freeze({
  "key": "client-supplied-images-for-site-sections",
  "title": "Client-Supplied Images for Site Sections",
  "family": "SITE_VISUAL_CONTENT",
  "lifecycle": "ACTIVE",
  "components": [
    "FRONTEND",
    "UI_UX"
  ],
  "contexts": [
    "HOMEPAGE",
    "SERVICES_PAGE",
    "SITE_IMAGE_CONTENT"
  ],
  "configuration": {
    "image_source": "client_supplied_photos",
    "image_selection_method": "agency_selects_suitable_photos",
    "stock_photo_replacement": "replace_client_identified_stock_photos_with_client_supplied_photos"
  },
  "ambiguities": [],
  "execution": {
    "status": "FAILED",
    "observed_behavior": "After the image-update claim, the client observed that identified stock photos still remained instead of the supplied photos."
  }
});
