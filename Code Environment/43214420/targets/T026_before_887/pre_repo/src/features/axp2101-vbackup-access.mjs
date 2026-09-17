export default Object.freeze({
  "requirement_id": "REQ_AXP_VBACKUP_ACCESS",
  "state_id": "REQ_AXP_VBACKUP_ACCESS_S001",
  "key": "axp2101-vbackup-access",
  "title": "AXP2101 VBACKUP Access",
  "family": "POWER_AND_BATTERY_SYSTEM",
  "lifecycle": "ACTIVE",
  "components": [
    "POWER",
    "PMIC",
    "PCB_LAYOUT"
  ],
  "contexts": [
    "AXP2101_BACKUP_POWER"
  ],
  "attributes": {
    "pin": "AXP2101 VBACKUP pin 27",
    "access_method": "small test pad or via",
    "purpose": "allow a backup capacitor or coin cell to be connected later for RTC retention or wake-from-off"
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_AXP_VBACKUP_ACCESS_E001"
  ],
  "render_hints": {
    "vbackupAccess": true,
    "vbackupLocationSpecified": false
  }
});
