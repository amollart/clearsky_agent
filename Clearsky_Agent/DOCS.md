# Home Assistant App: ClearSky Agent

## How to use
This app acts as a ClearSky snapshot agent. It fetches a full Home Assistant diagnostic overview via the REST API every 90 seconds and writes rotating snapshots to `/config/clearsky_snapshots/clearsky_snapshot_N.json`.

It also provides a web-based UI for managing warranty information for your Home Assistant devices. You can access this UI via the add-on's web interface.

The agent will:
- Periodically fetch and save Home Assistant diagnostic snapshots.
- Allow users to configure and track warranty information for devices through a web UI.
- Store warranty data persistently in `/data/warranty_data.json`.
