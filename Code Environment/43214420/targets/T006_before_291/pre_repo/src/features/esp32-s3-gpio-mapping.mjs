export default Object.freeze({
  "requirement_id": "REQ_ESP32_GPIO_MAPPING",
  "state_id": "REQ_ESP32_GPIO_MAPPING_S002",
  "key": "esp32-s3-gpio-mapping",
  "title": "ESP32-S3 GPIO Mapping",
  "family": "DIGITAL_CONNECTIVITY",
  "lifecycle": "ACTIVE",
  "components": [
    "MCU",
    "DIGITAL_IO"
  ],
  "contexts": [
    "GPIO_ASSIGNMENTS",
    "ESP32_S3"
  ],
  "attributes": {
    "five_v_enable_gpio": 3
  },
  "ambiguity": {
    "REQ_ESP32_GPIO_MAPPING_E002": {
      "status": "OPEN",
      "dimension": "VALUE",
      "description": "The retained GPIO arrangement uses GPIO22 and GPIO23, but the freelancer reports that those pins are unavailable on the ESP32-S3.",
      "source_event_id": "REQ_ESP32_GPIO_MAPPING_E002"
    }
  },
  "execution": null,
  "supporting_event_ids": [
    "REQ_ESP32_GPIO_MAPPING_E001",
    "REQ_ESP32_GPIO_MAPPING_E002"
  ],
  "render_hints": {}
});
