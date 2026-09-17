export default Object.freeze({
  "requirement_id": "REQ_AXP_VBACKUP_ACCESS",
  "state_id": "REQ_AXP_VBACKUP_ACCESS_S003",
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
    "purpose": "allow a backup capacitor or coin cell to be connected later for RTC retention or wake-from-off",
    "access_location": "beside the PWROK access point",
    "initial_population": "no backup component populated; expose only the pad"
  },
  "ambiguity": null,
  "execution": {
    "status": "CLAIMED_WORKING",
    "observed_behavior": "Freelancer reports adding a 2.54 mm pin header that exposes VBACKUP.",
    "source_event_id": "REQ_AXP_VBACKUP_ACCESS_E003"
  },
  "supporting_event_ids": [
    "REQ_AXP_VBACKUP_ACCESS_E001",
    "REQ_AXP_VBACKUP_ACCESS_E002",
    "REQ_AXP_VBACKUP_ACCESS_E003"
  ],
  "render_hints": {
    "vbackupAccess": true,
    "vbackupLocationSpecified": true
  }
});
