export default Object.freeze({
  "requirement_id": "REQ_DEVICE_ENCLOSURE",
  "state_id": "REQ_DEVICE_ENCLOSURE_S003",
  "key": "device-enclosure",
  "title": "Device Enclosure",
  "family": "PCB_ARCHITECTURE_AND_LAYOUT",
  "lifecycle": "ACTIVE",
  "components": [
    "MECHANICAL_DESIGN"
  ],
  "contexts": [
    "DEVICE_ENCLOSURE"
  ],
  "attributes": {
    "board_accommodation": [
      "power board",
      "main board",
      "sensor board"
    ],
    "battery_accommodation": "18650 battery",
    "cover_display_cutout": true,
    "cover_mounts": "display only",
    "display_connection_access": "easy to connect while installing the cover",
    "base_mounts": "mounts for every board and the battery",
    "sensor_air_intake_location": "bottom",
    "sensor_air_outlet_location": "top",
    "led_light_path_options": [
      "semi-transparent plexiglass strip",
      "light-transmitting grid pattern"
    ],
    "assembly": "simple to assemble",
    "component_retention": "secure every component in place even if the device is dropped"
  },
  "ambiguity": {
    "REQ_DEVICE_ENCLOSURE_E002": {
      "status": "OPEN",
      "dimension": "VALUE",
      "description": "The display size remains unresolved between 1.5 and 2.9 inches, affecting the enclosure cutout, and the LED light path remains unresolved between a semi-transparent plexiglass strip and a light-transmitting grid.",
      "source_event_id": "REQ_DEVICE_ENCLOSURE_E002"
    }
  },
  "execution": null,
  "supporting_event_ids": [
    "REQ_DEVICE_ENCLOSURE_E001",
    "REQ_DEVICE_ENCLOSURE_E002",
    "REQ_DEVICE_ENCLOSURE_E003"
  ],
  "render_hints": {}
});
