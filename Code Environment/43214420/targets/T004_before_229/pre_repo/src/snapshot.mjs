import feature001 from "./features/battery-charge-status-output.mjs";
import feature002 from "./features/battery-connector-interface.mjs";
import feature003 from "./features/battery-safety-protection.mjs";
import feature004 from "./features/connector-pin-labels.mjs";
import feature005 from "./features/esp32-sleep-and-wake-behavior.mjs";
import feature006 from "./features/i2c-bus-conditioning.mjs";
import feature007 from "./features/interboard-power-interface.mjs";
import feature008 from "./features/interboard-signal-interface.mjs";
import feature009 from "./features/native-usb-programming.mjs";
import feature010 from "./features/pcb-architecture-variants.mjs";
import feature011 from "./features/power-board-layer-stack-and-grounding.mjs";
import feature012 from "./features/power-board-mechanical-form-factor.mjs";
import feature013 from "./features/production-component-sourceability.mjs";
import feature014 from "./features/sensor-board-connector-hub.mjs";
import feature015 from "./features/software-switched-5v-rail.mjs";
import { buildProfile } from "./profile.mjs";

const features = Object.freeze([feature001, feature002, feature003, feature004, feature005, feature006, feature007, feature008, feature009, feature010, feature011, feature012, feature013, feature014, feature015]);
const stateMap = Object.freeze(Object.fromEntries(features.map((feature) => [feature.requirement_id, feature.state_id])));

export const profile = buildProfile(features);
export const snapshot = Object.freeze({ environment: "reconstructed-pre-event", features, stateMap });
