export default Object.freeze({
  "requirement_id": "REQ_I2C_BUS_CONDITIONING",
  "state_id": "REQ_I2C_BUS_CONDITIONING_S002",
  "key": "i2c-bus-conditioning",
  "title": "I2C Bus Conditioning",
  "family": "DIGITAL_CONNECTIVITY",
  "lifecycle": "ACTIVE",
  "components": [
    "I2C"
  ],
  "contexts": [
    "INTERBOARD_CABLING"
  ],
  "attributes": {
    "interboard_cable_length": {
      "maximum_cm": 15
    },
    "bus_speed_khz": 400,
    "pull_up_resistance_ohms": 2200,
    "pull_up_location": "MAIN_BOARD"
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_I2C_BUS_CONDITIONING_E001",
    "REQ_I2C_BUS_CONDITIONING_E002"
  ],
  "render_hints": {}
});
