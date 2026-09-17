export default Object.freeze({
  "requirement_id": "REQ_LED_ARRAY_BOARD",
  "state_id": "REQ_LED_ARRAY_BOARD_S006",
  "key": "addressable-led-array-board",
  "title": "Addressable LED Array Board",
  "family": "PERIPHERAL_AND_SENSOR_INTERFACES",
  "lifecycle": "ACTIVE",
  "components": [
    "PCB_LAYOUT",
    "LED"
  ],
  "contexts": [
    "LED_BOARD"
  ],
  "attributes": {
    "addressable_led_count": 8,
    "led_lcsc_part_number": "C5149201",
    "led_model": "SK6812MINI-E",
    "led_manufacturer": "OPSCO Optoelectronics",
    "led_package": "3228",
    "led_package_dimensions": "3.2×2.8mm",
    "led_mounting": "4-pad SMD",
    "led_color_channels": "RGBW"
  },
  "ambiguity": {
    "REQ_LED_ARRAY_BOARD_E002": {
      "status": "OPEN",
      "dimension": "VALUE",
      "description": "The required spacing between LEDs on the LED board is unspecified.",
      "source_event_id": "REQ_LED_ARRAY_BOARD_E002"
    }
  },
  "execution": null,
  "supporting_event_ids": [
    "REQ_LED_ARRAY_BOARD_E001",
    "REQ_LED_ARRAY_BOARD_E002",
    "REQ_LED_ARRAY_BOARD_E004",
    "REQ_LED_ARRAY_BOARD_E006"
  ],
  "render_hints": {}
});
