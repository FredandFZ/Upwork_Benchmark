import feature001 from "./features/battery-charge-status-output.mjs";
import feature002 from "./features/battery-connector-interface.mjs";
import feature003 from "./features/battery-safety-protection.mjs";
import feature004 from "./features/esp32-sleep-and-wake-behavior.mjs";
import feature005 from "./features/i2c-bus-conditioning.mjs";
import feature006 from "./features/native-usb-programming.mjs";
import feature007 from "./features/pcb-architecture-variants.mjs";
import feature008 from "./features/power-board-mechanical-form-factor.mjs";
import feature009 from "./features/production-component-sourceability.mjs";
import feature010 from "./features/software-switched-5v-rail.mjs";
import { buildProfile } from "./profile.mjs";

const features = Object.freeze([feature001, feature002, feature003, feature004, feature005, feature006, feature007, feature008, feature009, feature010]);
const stateMap = Object.freeze(Object.fromEntries(features.map((feature) => [feature.requirement_id, feature.state_id])));

export const profile = buildProfile(features);
export const snapshot = Object.freeze({ environment: "reconstructed-pre-event", features, stateMap });
