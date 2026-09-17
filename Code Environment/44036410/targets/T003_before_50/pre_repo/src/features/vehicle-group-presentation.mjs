export default Object.freeze({
  "requirement_id": "REQ_VEHICLE_GROUP_PRESENTATION",
  "state_id": "REQ_VEHICLE_GROUP_PRESENTATION_S002",
  "key": "vehicle-group-presentation",
  "title": "Vehicle Group Presentation",
  "family": "FRONT_PAGE_PRESENTATION",
  "lifecycle": "OBSERVED",
  "components": [],
  "contexts": [],
  "attributes": {
    "display_format": "clean fixed vehicle-group line or customer-tailored vehicle-assessed line",
    "use_checkbox_form": false
  },
  "ambiguity": null,
  "execution": {
    "status": "FAILED",
    "observed_behavior": "The current vehicle-group section uses checkboxes beside the vehicle options, making it look like an uncompleted form rather than a finished customer report.",
    "source_event_id": "REQ_VEHICLE_GROUP_PRESENTATION_E002"
  },
  "supporting_event_ids": [
    "REQ_VEHICLE_GROUP_PRESENTATION_E001",
    "REQ_VEHICLE_GROUP_PRESENTATION_E002"
  ],
  "render_hints": {
    "vehicleUsesCheckboxes": true
  }
});
