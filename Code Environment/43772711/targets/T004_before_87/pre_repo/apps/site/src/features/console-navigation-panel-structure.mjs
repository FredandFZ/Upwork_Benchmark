export default Object.freeze({
  "key": "console-navigation-panel-structure",
  "title": "Console Navigation Panel Structure",
  "family": "CONSOLE_UI",
  "lifecycle": "ACTIVE",
  "components": [
    "FRONTEND",
    "UI_UX"
  ],
  "contexts": [
    "CONSOLE_NAVIGATION",
    "APP_NAVIGATION"
  ],
  "configuration": {
    "shell_navigation_panel": {
      "behavior": "collapsible",
      "current_position": "left"
    },
    "app_navigation_panel": {
      "availability": "certain applications",
      "behavior": "collapsible",
      "example_position": "left"
    },
    "concurrent_panel_case": "Determine an appropriate arrangement when shell and application panels are both present."
  },
  "ambiguities": [
    {
      "status": "OPEN",
      "dimension": "VALUE",
      "description": "The client questions placing shell and app panels on opposite sides but does not confirm whether app navigation should instead be nested within one side panel or which side the shell panel should occupy."
    }
  ],
  "execution": null
});
