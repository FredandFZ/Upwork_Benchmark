export default Object.freeze({
  "requirement_id": "REQ_ESP32_GPIO_MAPPING",
  "state_id": "REQ_ESP32_GPIO_MAPPING_S001",
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
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_ESP32_GPIO_MAPPING_E001"
  ],
  "render_hints": {}
});
