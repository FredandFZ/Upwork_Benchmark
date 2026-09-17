export default Object.freeze({
  "requirement_id": "REQ_SENSOR_BOARD_CONNECTOR_HUB",
  "state_id": "REQ_SENSOR_BOARD_CONNECTOR_HUB_S004",
  "key": "sensor-board-connector-hub",
  "title": "Sensor Board Connector Hub",
  "family": "PERIPHERAL_AND_SENSOR_INTERFACES",
  "lifecycle": "ACTIVE",
  "components": [
    "CONNECTORS",
    "SENSOR_INTERFACE"
  ],
  "contexts": [
    "SENSOR_BOARD",
    "SENSOR_MODULES"
  ],
  "attributes": {
    "board_role": "connector hub for sensors",
    "main_board_input_connectors": [
      {
        "function": "power",
        "connector": "4-pin JST-PH 2.0mm",
        "pins": [
          "5V",
          "GND",
          "3V3",
          "GND"
        ]
      },
      {
        "function": "signals",
        "connector": "6-pin JST-[FREELANCER_NAME_002] 1.25mm",
        "pins": [
          "SDA0",
          "SCL0",
          "SDA1",
          "SCL1",
          "UART TX",
          "UART RX"
        ]
      }
    ],
    "module_output_connectors": [
      {
        "module": "SCD41",
        "connector": "4-pin JST-[FREELANCER_NAME_002]",
        "pins": [
          "3V3",
          "GND",
          "SDA0",
          "SCL0"
        ]
      },
      {
        "module": "BME280",
        "connector": "4-pin JST-[FREELANCER_NAME_002]"
      },
      {
        "module": "ENS160",
        "connector": "4-pin JST-[FREELANCER_NAME_002]"
      },
      {
        "module": "SPS30",
        "connector": "5-pin JST-ZH 1.5mm",
        "pins": [
          "5V",
          "SDA0",
          "SCL0",
          "SEL→GND",
          "GND"
        ]
      },
      {
        "module": "ZE08-CH2O",
        "connector": "7-pin JST-[FREELANCER_NAME_002]",
        "cable_compatibility": "match the supplied cable"
      },
      {
        "module": "I2C display",
        "connector": "4-pin JST-[FREELANCER_NAME_002]",
        "pins": [
          "3V3",
          "GND",
          "SDA1",
          "SCL1"
        ]
      },
      {
        "module": "spare I2C0 port",
        "connector": "4-pin JST-[FREELANCER_NAME_002]"
      },
      {
        "module": "spare I2C1 port",
        "connector": "4-pin JST-[FREELANCER_NAME_002]"
      }
    ],
    "total_connector_count": 10
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_SENSOR_BOARD_CONNECTOR_HUB_E001",
    "REQ_SENSOR_BOARD_CONNECTOR_HUB_E003",
    "REQ_SENSOR_BOARD_CONNECTOR_HUB_E004"
  ],
  "render_hints": {}
});
