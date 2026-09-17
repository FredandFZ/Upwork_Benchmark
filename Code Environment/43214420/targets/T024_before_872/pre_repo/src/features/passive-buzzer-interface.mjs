export default Object.freeze({
  "requirement_id": "REQ_PASSIVE_BUZZER_INTERFACE",
  "state_id": "REQ_PASSIVE_BUZZER_INTERFACE_S004",
  "key": "passive-buzzer-interface",
  "title": "Passive Buzzer Interface",
  "family": "PERIPHERAL_AND_SENSOR_INTERFACES",
  "lifecycle": "ACTIVE",
  "components": [
    "AUDIO",
    "DIGITAL_IO"
  ],
  "contexts": [
    "BUZZER"
  ],
  "attributes": {
    "buzzer_type": "passive",
    "prototype_part_usage": "Use the AliExpress buzzer for prototyping",
    "production_part_policy": "A suitable alternative available from LCSC is acceptable",
    "approved_production_buzzer": "Freelancer-proposed option in message 475"
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_PASSIVE_BUZZER_INTERFACE_E001",
    "REQ_PASSIVE_BUZZER_INTERFACE_E003",
    "REQ_PASSIVE_BUZZER_INTERFACE_E004"
  ],
  "render_hints": {}
});
