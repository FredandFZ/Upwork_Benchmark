export default Object.freeze({
  "requirement_id": "REQ_STANDALONE_USB_3V3_POWER",
  "state_id": "REQ_STANDALONE_USB_3V3_POWER_S002",
  "key": "standalone-usb-3-3v-power",
  "title": "Standalone USB 3.3V Power",
  "family": "POWER_AND_BATTERY_SYSTEM",
  "lifecycle": "ACTIVE",
  "components": [
    "POWER",
    "USB"
  ],
  "contexts": [
    "STANDALONE_PROGRAMMING",
    "USB_POWER",
    "SENSOR_DEBUGGING"
  ],
  "attributes": {
    "usb_power_regulator": "ME6211A LDO, 1A",
    "activation_condition": "Main-board USB-C connected while the power board is disconnected",
    "powered_rail": "Complete 3.3V rail",
    "powered_loads": [
      "ESP32-S3 module",
      "INA219",
      "SCD41",
      "BME280",
      "ENS160",
      "I2C display",
      "TTP223",
      "AM312 PIR"
    ],
    "source_selection": "Schottky-diode OR-ing between available 3.3V sources",
    "purpose": "Standalone programming",
    "usb_power_regulator_location": "MAIN_BOARD"
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_STANDALONE_USB_3V3_POWER_E001",
    "REQ_STANDALONE_USB_3V3_POWER_E002"
  ],
  "render_hints": {}
});
