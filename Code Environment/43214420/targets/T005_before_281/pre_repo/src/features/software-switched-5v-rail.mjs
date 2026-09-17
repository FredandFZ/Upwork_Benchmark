export default Object.freeze({
  "requirement_id": "REQ_SWITCHED_5V_RAIL",
  "state_id": "REQ_SWITCHED_5V_RAIL_S005",
  "key": "software-switched-5v-rail",
  "title": "Software-Switched 5V Rail",
  "family": "POWER_AND_BATTERY_SYSTEM",
  "lifecycle": "ACTIVE",
  "components": [
    "POWER",
    "MCU"
  ],
  "contexts": [
    "FIVE_VOLT_RAIL",
    "SENSOR_POWER",
    "LED_POWER"
  ],
  "attributes": {
    "enable_gpio": "GPIO3",
    "enable_control": "ESP32 software-controlled boost enable",
    "boost_converter": "MT3608",
    "enable_pull_down": "100kΩ to GND",
    "default_state": "off unless enabled by the ESP32",
    "sensor_power_purpose": "supply sensors that require 5V",
    "operation_pattern": "enabled only at intervals rather than continuously",
    "rated_output_current": "500mA",
    "five_volt_sensor_loads": [
      "SPS30 particulate sensor",
      "ZE08-CH2O formaldehyde sensor"
    ],
    "led_load_power": "SK6812 LEDs when configured for 5V operation"
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_SWITCHED_5V_RAIL_E001",
    "REQ_SWITCHED_5V_RAIL_E002",
    "REQ_SWITCHED_5V_RAIL_E003",
    "REQ_SWITCHED_5V_RAIL_E004",
    "REQ_SWITCHED_5V_RAIL_E005"
  ],
  "render_hints": {}
});
