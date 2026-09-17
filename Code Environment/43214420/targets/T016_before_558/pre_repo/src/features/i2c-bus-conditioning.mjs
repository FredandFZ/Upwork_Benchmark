export default Object.freeze({
  "requirement_id": "REQ_I2C_BUS_CONDITIONING",
  "state_id": "REQ_I2C_BUS_CONDITIONING_S006",
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
      "minimum_cm": 10,
      "maximum_cm": 20
    },
    "bus_speed_khz": 400,
    "pull_up_resistance_ohms": 2200,
    "pull_up_location": "MAIN_BOARD",
    "series_resistor_resistance_ohms": 22,
    "series_resistor_population_policy": "OPTIONAL",
    "series_resistor_position": "DIRECTLY_AT_ESP32_S3_PINS_UPSTREAM_OF_PULL_UPS_AND_DEVICES"
  },
  "ambiguity": null,
  "execution": {
    "status": "CLAIMED_WORKING",
    "observed_behavior": "Freelancer confirms that all I2C pull-up resistors in the design are 2.2 kΩ.",
    "source_event_id": "REQ_I2C_BUS_CONDITIONING_E006"
  },
  "supporting_event_ids": [
    "REQ_I2C_BUS_CONDITIONING_E001",
    "REQ_I2C_BUS_CONDITIONING_E002",
    "REQ_I2C_BUS_CONDITIONING_E004",
    "REQ_I2C_BUS_CONDITIONING_E005",
    "REQ_I2C_BUS_CONDITIONING_E006"
  ],
  "render_hints": {}
});
