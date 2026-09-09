export default Object.freeze({
  "key": "ruler-magnifier-interaction",
  "title": "Ruler Magnifier Interaction",
  "family": "MEASUREMENT_INTERFACE",
  "lifecycle": "ACTIVE",
  "components": [
    "UI_UX"
  ],
  "contexts": [
    "SCOLIOMETER_MEASUREMENT"
  ],
  "configuration": {
    "magnifier_position": "over the ruler",
    "magnifier_movement": "along the ruler's path"
  },
  "ambiguities": [],
  "execution": {
    "status": "FAILED",
    "observed_behavior": "The client rejects the presented magnifier design as incorrect and states that the magnifier must sit over the ruler and move along its path."
  }
});
