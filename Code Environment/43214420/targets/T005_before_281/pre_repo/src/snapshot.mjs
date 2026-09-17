import feature001 from "./features/addressable-led-array-board.mjs";
import feature002 from "./features/addressable-led-power-and-data-interface.mjs";
import feature003 from "./features/axp2101-power-management.mjs";
import feature004 from "./features/battery-charge-status-output.mjs";
import feature005 from "./features/battery-connector-interface.mjs";
import feature006 from "./features/battery-safety-protection.mjs";
import feature007 from "./features/connector-pin-labels.mjs";
import feature008 from "./features/dcdc1-output-regulation.mjs";
import feature009 from "./features/esp32-s3-gpio-mapping.mjs";
import feature010 from "./features/esp32-sleep-and-wake-behavior.mjs";
import feature011 from "./features/i2c-bus-conditioning.mjs";
import feature012 from "./features/interboard-power-interface.mjs";
import feature013 from "./features/interboard-signal-interface.mjs";
import feature014 from "./features/native-usb-programming.mjs";
import feature015 from "./features/pcb-architecture-variants.mjs";
import feature016 from "./features/power-board-layer-stack-and-grounding.mjs";
import feature017 from "./features/power-board-mechanical-form-factor.mjs";
import feature018 from "./features/production-component-sourceability.mjs";
import feature019 from "./features/sensor-board-connector-hub.mjs";
import feature020 from "./features/software-switched-5v-rail.mjs";
import feature021 from "./features/standalone-usb-3-3v-power.mjs";
import { buildProfile } from "./profile.mjs";

const features = Object.freeze([feature001, feature002, feature003, feature004, feature005, feature006, feature007, feature008, feature009, feature010, feature011, feature012, feature013, feature014, feature015, feature016, feature017, feature018, feature019, feature020, feature021]);
const stateMap = Object.freeze(Object.fromEntries(features.map((feature) => [feature.requirement_id, feature.state_id])));

export const profile = buildProfile(features);
export const snapshot = Object.freeze({ environment: "reconstructed-pre-event", features, stateMap });
