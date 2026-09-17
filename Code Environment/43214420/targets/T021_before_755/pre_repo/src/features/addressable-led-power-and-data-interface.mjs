export default Object.freeze({
  "requirement_id": "REQ_ADDRESSABLE_LED_ELECTRICAL_INTERFACE",
  "state_id": "REQ_ADDRESSABLE_LED_ELECTRICAL_INTERFACE_S010",
  "key": "addressable-led-power-and-data-interface",
  "title": "Addressable LED Power and Data Interface",
  "family": "PERIPHERAL_AND_SENSOR_INTERFACES",
  "lifecycle": "ACTIVE",
  "components": [
    "LED",
    "POWER",
    "DIGITAL_IO"
  ],
  "contexts": [
    "ADDRESSABLE_LEDS",
    "STATUS_LIGHTING"
  ],
  "attributes": {
    "led_supply_voltage": "3.3V",
    "level_shifter_required": false,
    "led_power_control": "independent from sensor power control",
    "disabled_standby_current_target": "zero",
    "data_high_threshold": "2.31V at 3.3V LED supply",
    "selected_led_model": "SK6812MINI-E",
    "selected_led_lcsc_part_number": "C5149201",
    "selected_led_manufacturer": "OPSCO Optoelectronics",
    "selected_led_package": "3228 (3.2×2.8mm), 4-pad SMD, RGBW",
    "data_drive": "directly from the ESP32 3.3V output",
    "accepted_operating_condition": "Reliable at indicator brightness levels despite operating below the 3.7V datasheet minimum"
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_ADDRESSABLE_LED_ELECTRICAL_INTERFACE_E001",
    "REQ_ADDRESSABLE_LED_ELECTRICAL_INTERFACE_E002",
    "REQ_ADDRESSABLE_LED_ELECTRICAL_INTERFACE_E006",
    "REQ_ADDRESSABLE_LED_ELECTRICAL_INTERFACE_E008",
    "REQ_ADDRESSABLE_LED_ELECTRICAL_INTERFACE_E009",
    "REQ_ADDRESSABLE_LED_ELECTRICAL_INTERFACE_E010"
  ],
  "render_hints": {}
});
