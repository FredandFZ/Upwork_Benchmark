export default Object.freeze({
  "requirement_id": "REQ_ADDRESSABLE_LED_ELECTRICAL_INTERFACE",
  "state_id": "REQ_ADDRESSABLE_LED_ELECTRICAL_INTERFACE_S008",
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
    "led_supply_voltage": "5V",
    "level_shifter_required": true,
    "led_power_control": "independent from sensor power control",
    "disabled_standby_current_target": "zero",
    "data_level_shifter_component": "74AHCT1G125",
    "level_shifter_lcsc_part_number": "C151417",
    "data_high_threshold": "3.5V at 5V LED supply",
    "selected_led_model": "SK6812MINI-E",
    "selected_led_lcsc_part_number": "C5149201",
    "selected_led_manufacturer": "OPSCO Optoelectronics",
    "selected_led_package": "3228 (3.2×2.8mm), 4-pad SMD, RGBW"
  },
  "ambiguity": {
    "REQ_ADDRESSABLE_LED_ELECTRICAL_INTERFACE_E007": {
      "status": "OPEN",
      "dimension": "VALUE",
      "description": "It is unresolved whether the revised independent LED power path eliminates the data level shifter.",
      "source_event_id": "REQ_ADDRESSABLE_LED_ELECTRICAL_INTERFACE_E007"
    }
  },
  "execution": null,
  "supporting_event_ids": [
    "REQ_ADDRESSABLE_LED_ELECTRICAL_INTERFACE_E001",
    "REQ_ADDRESSABLE_LED_ELECTRICAL_INTERFACE_E002",
    "REQ_ADDRESSABLE_LED_ELECTRICAL_INTERFACE_E004",
    "REQ_ADDRESSABLE_LED_ELECTRICAL_INTERFACE_E006",
    "REQ_ADDRESSABLE_LED_ELECTRICAL_INTERFACE_E007",
    "REQ_ADDRESSABLE_LED_ELECTRICAL_INTERFACE_E008"
  ],
  "render_hints": {}
});
