export function mechanicalEnvelope(profile) {
  return Object.freeze({ width_mm: profile.boardWidthMm, height_mm: profile.boardHeightMm, mounting_holes: profile.mountingHoleCount, board_count: profile.boardCount });
}

export function connectorLayout(profile) {
  return Object.freeze({ top_edge_aligned: profile.connectorTopAligned, lower_connectors_upward: profile.lowerConnectorsUpward, battery_ntc_contact: profile.batteryNtcContact, battery_connector_orientation: profile.batteryConnectorOrientation });
}

export function breakoutStatus(profile) {
  return Object.freeze({ full_pin_breakout: profile.fullPinBreakout, pin_count: profile.breakoutPinCount, through_hole: profile.throughHoleBreakout });
}

export function powerSafety(profile) {
  return Object.freeze({ protection_specified: profile.batteryProtectionSpecified, overcharge_cutoff_specified: profile.overchargeCutoffSpecified, vrtc: profile.vrtcHandling, vbackup_access: profile.vbackupAccess, vbackup_location_specified: profile.vbackupLocationSpecified });
}

export function inputInterfaces(profile) {
  return Object.freeze({ touch_inputs: profile.touchInputCount, pir_input: profile.pirInputPresent, panel_inputs: profile.panelInputCount, bias_specified: profile.inputBiasSpecified });
}

export function manufacturingStatus(profile) {
  return Object.freeze({ bom_status: profile.bomStatus, runtime_failures: profile.diagnostics.filter((item) => item.status === "FAILED").length });
}
