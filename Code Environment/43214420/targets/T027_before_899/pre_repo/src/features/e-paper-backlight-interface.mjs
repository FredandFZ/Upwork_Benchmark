export default Object.freeze({
  "requirement_id": "REQ_EPAPER_BACKLIGHT",
  "state_id": "REQ_EPAPER_BACKLIGHT_S004",
  "key": "e-paper-backlight-interface",
  "title": "E-Paper Backlight Interface",
  "family": "PERIPHERAL_AND_SENSOR_INTERFACES",
  "lifecycle": "ACTIVE",
  "components": [
    "LED",
    "POWER",
    "DIGITAL_IO"
  ],
  "contexts": [
    "EPAPER_BACKLIGHT"
  ],
  "attributes": {
    "required": true,
    "purpose": "provide external backlighting for the e-paper display",
    "supported_light_sources": [
      "5V COB strip",
      "future 3.3V frontlight module"
    ],
    "current_supply_selection": "5V through populated Pin 1 jumper",
    "future_3v3_jumper": "footprint present but unpopulated",
    "switch_topology": "BSS138 low-side switch",
    "brightness_control": "GPIO42 PWM",
    "gate_resistor": "10kΩ",
    "gate_pulldown": "10kΩ",
    "boot_behavior": "LED remains off while booting",
    "pwm_decoupling": "4.7µF X5R 0603 capacitor between Pin 1 and GND",
    "series_resistor_footprint": "DNP",
    "flyback_diode": "not included",
    "estimated_maximum_current": "~70mA"
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_EPAPER_BACKLIGHT_E001",
    "REQ_EPAPER_BACKLIGHT_E003",
    "REQ_EPAPER_BACKLIGHT_E004"
  ],
  "render_hints": {}
});
