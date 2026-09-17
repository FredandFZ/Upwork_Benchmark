export default Object.freeze({
  "requirement_id": "REQ_ESP32_SLEEP_WAKE_BEHAVIOR",
  "state_id": "REQ_ESP32_SLEEP_WAKE_BEHAVIOR_S001",
  "key": "esp32-sleep-and-wake-behavior",
  "title": "ESP32 Sleep and Wake Behavior",
  "family": "POWER_AND_BATTERY_SYSTEM",
  "lifecycle": "ACTIVE",
  "components": [
    "MCU",
    "POWER"
  ],
  "contexts": [
    "ESP32_LOW_POWER"
  ],
  "attributes": {
    "maximum_active_clock_mhz": 160,
    "idle_clock_mhz": 80,
    "idle_sleep_mode": "automatic light sleep",
    "current_deep_sleep_entry_conditions": [
      "critical battery",
      "false wake"
    ],
    "deep_sleep_current": "~10µA",
    "timer_wake_interval": "5min",
    "touch_wake_gpio": 26,
    "touch_wake_mode": "ext0",
    "final_deep_sleep_policy": "remain in deep sleep most of the time and wake only for updates"
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_ESP32_SLEEP_WAKE_BEHAVIOR_E001"
  ],
  "render_hints": {}
});
