export default Object.freeze({
  "requirement_id": "REQ_ADDRESSABLE_LED_ELECTRICAL_INTERFACE",
  "state_id": "REQ_ADDRESSABLE_LED_ELECTRICAL_INTERFACE_S002",
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
    "led_supply_voltage": "5V unless the selected LED supports 3.3V power and logic",
    "level_shifter_required": "required with a 5V LED supply; potentially unnecessary with a 3.3V-compatible LED",
    "led_power_control": "GPIO3-controlled shutdown of the complete 5V rail when the LEDs are unnecessary",
    "disabled_standby_current_target": "zero"
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_ADDRESSABLE_LED_ELECTRICAL_INTERFACE_E001",
    "REQ_ADDRESSABLE_LED_ELECTRICAL_INTERFACE_E002"
  ],
  "render_hints": {}
});
