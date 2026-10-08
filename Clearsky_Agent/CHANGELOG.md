<!-- https://developers.home-assistant.io/docs/apps/presentation#keeping-a-changelog -->
## 0.2.2

- Add N/A warranty state for devices without warranty information
- Add N/A filter option and statistics counter in web dashboard
- Fix deprecated map option to use homeassistant_config
- Add container SAS URL support for snapshot history in direct Azure mode
- Implement Azure Blob Storage REST API integration for history tab

## 0.2.1

- Add Azure Blob Storage synchronization for snapshots (dual-sync: latest.json & historical archives).
- Add configurable options for Azure connection string and container name.
- Add `/api/status` endpoint to monitor sync health and configuration.
- Add companion Web Dashboard for viewing snapshots in Azure.

## 0.0.2

- Add snapshot generation functionality.
- Add web UI for managing device warranty information.

## 0.0.1

- Initial release of the ClearSky Agent.
- Forked from the official Home Assistant example app.
