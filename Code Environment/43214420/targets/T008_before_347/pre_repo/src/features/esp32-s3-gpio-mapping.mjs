export default Object.freeze({
  "requirement_id": "REQ_ESP32_GPIO_MAPPING",
  "state_id": "REQ_ESP32_GPIO_MAPPING_S007",
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
    "five_v_enable_gpio": 5,
    "scl0_gpio": 38,
    "spi_mosi_gpio": 47,
    "candidate_gpio_pool": "GPIO0–GPIO21 subject to strapping-pin caveats; GPIO38–GPIO44; GPIO47; GPIO48"
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_ESP32_GPIO_MAPPING_E001",
    "REQ_ESP32_GPIO_MAPPING_E003",
    "REQ_ESP32_GPIO_MAPPING_E007"
  ],
  "render_hints": {}
});
