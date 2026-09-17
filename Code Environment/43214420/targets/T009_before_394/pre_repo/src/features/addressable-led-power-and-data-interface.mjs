export default Object.freeze({
  "requirement_id": "REQ_ADDRESSABLE_LED_ELECTRICAL_INTERFACE",
  "state_id": "REQ_ADDRESSABLE_LED_ELECTRICAL_INTERFACE_S004",
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
    "led_power_control": "GPIO5-controlled shutdown of the complete 5V rail when the LEDs are unnecessary",
    "disabled_standby_current_target": "zero",
    "data_level_shifter_component": "74AHCT1G125",
    "level_shifter_lcsc_part_number": "C151417",
    "data_high_threshold": "3.5V at 5V LED supply"
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_ADDRESSABLE_LED_ELECTRICAL_INTERFACE_E001",
    "REQ_ADDRESSABLE_LED_ELECTRICAL_INTERFACE_E002",
    "REQ_ADDRESSABLE_LED_ELECTRICAL_INTERFACE_E003",
    "REQ_ADDRESSABLE_LED_ELECTRICAL_INTERFACE_E004"
  ],
  "render_hints": {}
});
