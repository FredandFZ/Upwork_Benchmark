export default Object.freeze({
  "requirement_id": "REQ_SPS30_I2C_MODE",
  "state_id": "REQ_SPS30_I2C_MODE_S002",
  "key": "sps30-i2c-mode-selection",
  "title": "SPS30 I2C Mode Selection",
  "family": "PERIPHERAL_AND_SENSOR_INTERFACES",
  "lifecycle": "ACTIVE",
  "components": [
    "SENSOR_INTERFACE",
    "I2C"
  ],
  "contexts": [
    "SPS30"
  ],
  "attributes": {
    "sel_pin_connection": "GND",
    "operating_mode": "I2C"
  },
  "ambiguity": null,
  "execution": {
    "status": "CLAIMED_WORKING",
    "observed_behavior": "Freelancer reports that the submitted design document shows the SPS30 SEL pin connected to ground.",
    "source_event_id": "REQ_SPS30_I2C_MODE_E002"
  },
  "supporting_event_ids": [
    "REQ_SPS30_I2C_MODE_E001",
    "REQ_SPS30_I2C_MODE_E002"
  ],
  "render_hints": {}
});
