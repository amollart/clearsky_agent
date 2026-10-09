#!/usr/bin/env python3
"""
ClearSky snapshot agent fetches full HA diagnostic overview via REST API
every 90s and writes rotating snapshots to /config/clearsky_snapshots/clearsky_snapshot_N.json.
"""

import asyncio
import json
import os
import logging
import aiohttp
from aiohttp import web
import signal
import sys
from datetime import datetime, timezone

# Try importing Azure Storage SDK
try:
    from azure.storage.blob import BlobServiceClient, ContentSettings
    AZURE_SDK_AVAILABLE = True
except ImportError:
    BlobServiceClient = None
    ContentSettings = None
    AZURE_SDK_AVAILABLE = False

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
_LOGGER = logging.getLogger(__name__)

# Supervisor‑provided token and internal proxy URL (no user config needed)
HA_URL = "http://supervisor/core/api"
HA_TOKEN = os.getenv("SUPERVISOR_TOKEN") or os.getenv("HASSIO_TOKEN")
WARRANTY_DATA_PATH = "/data/warranty_data.json"
WS_URL = "ws://supervisor/core/websocket" # Moved to global scope

def load_addon_config():
    """Read configuration from /data/options.json with fallback to environment variables."""
    config = {
        "poll_interval": 90,
        # Platform Configuration (Phase 1)
        "platform_enabled": False,
        "platform_api_url": "",
        "registration_token": "",
        "instance_name": "My Home",
        # Legacy Direct Azure Upload (backward compatible)
        "azure_upload_enabled": True,
        "azure_storage_connection_string": "",
        "azure_container_name": "clearsky-snapshots",
    }
    if os.path.exists("/data/options.json"):
        try:
            with open("/data/options.json", "r", encoding="utf-8") as f:
                opts = json.load(f)
                if "poll_interval" in opts and opts["poll_interval"]:
                    config["poll_interval"] = int(opts["poll_interval"])
                # Platform config
                if "platform_enabled" in opts:
                    config["platform_enabled"] = bool(opts["platform_enabled"])
                if "platform_api_url" in opts and opts["platform_api_url"]:
                    config["platform_api_url"] = str(opts["platform_api_url"]).strip()
                if "registration_token" in opts and opts["registration_token"]:
                    config["registration_token"] = str(opts["registration_token"]).strip()
                if "instance_name" in opts and opts["instance_name"]:
                    config["instance_name"] = str(opts["instance_name"]).strip()
                # Legacy Azure config
                if "azure_upload_enabled" in opts:
                    config["azure_upload_enabled"] = bool(opts["azure_upload_enabled"])
                if "azure_storage_connection_string" in opts and opts["azure_storage_connection_string"]:
                    config["azure_storage_connection_string"] = str(opts["azure_storage_connection_string"]).strip()
                if "azure_container_name" in opts and opts["azure_container_name"]:
                    config["azure_container_name"] = str(opts["azure_container_name"]).strip()
        except Exception as e:
            _LOGGER.warning(f"Could not read options.json, using default: {e}")

    # Environment variable fallbacks/overrides
    if os.getenv("POLL_INTERVAL"):
        try:
            config["poll_interval"] = int(os.getenv("POLL_INTERVAL"))
        except ValueError:
            pass
    if os.getenv("PLATFORM_ENABLED"):
        config["platform_enabled"] = os.getenv("PLATFORM_ENABLED").lower() in ("true", "1", "yes")
    if os.getenv("PLATFORM_API_URL"):
        config["platform_api_url"] = os.getenv("PLATFORM_API_URL").strip()
    if os.getenv("REGISTRATION_TOKEN"):
        config["registration_token"] = os.getenv("REGISTRATION_TOKEN").strip()
    if os.getenv("INSTANCE_NAME"):
        config["instance_name"] = os.getenv("INSTANCE_NAME").strip()
    if os.getenv("AZURE_UPLOAD_ENABLED"):
        config["azure_upload_enabled"] = os.getenv("AZURE_UPLOAD_ENABLED").lower() in ("true", "1", "yes")
    if os.getenv("AZURE_STORAGE_CONNECTION_STRING"):
        config["azure_storage_connection_string"] = os.getenv("AZURE_STORAGE_CONNECTION_STRING").strip()
    if os.getenv("AZURE_CONTAINER_NAME"):
        config["azure_container_name"] = os.getenv("AZURE_CONTAINER_NAME").strip()

    return config

# In-memory status tracker for Azure sync
azure_upload_status = {
    "last_status": "unconfigured",
    "last_success": None,
    "last_attempt": None,
    "last_error": None,
    "blobs_written": []
}

# In-memory status tracker for Platform sync
platform_upload_status = {
    "last_status": "disabled",
    "last_success": None,
    "last_attempt": None,
    "last_error": None,
    "registered": False,
    "instance_id": None
}

# Global shutdown event
shutdown_event = asyncio.Event()

def load_warranty_data():
    """Load warranty info from persistent storage."""
    if os.path.exists(WARRANTY_DATA_PATH):
        try:
            with open(WARRANTY_DATA_PATH, "r") as f:
                return json.load(f)
        except Exception as e:
            _LOGGER.error(f"Error loading warranty data: {e}")
    return {}

def save_warranty_data(data):
    """Save warranty info to persistent storage."""
    try:
        with open(WARRANTY_DATA_PATH, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        _LOGGER.error(f"Error saving warranty data: {e}")

async def _get_ha_registries():
    """Fetch registries via WebSocket for internal mapping."""
    try:
        _LOGGER.debug("WebSocket: Attempting to connect to %s", WS_URL)
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(WS_URL) as ws:
                _LOGGER.debug("WebSocket: Connected. Waiting for auth_required.")
                # 1. Wait for 'auth_required'
                try:
                    msg = await asyncio.wait_for(ws.receive_json(), timeout=5.0)
                except asyncio.TimeoutError:
                    _LOGGER.error("WebSocket: Timeout waiting for auth_required message.")
                    return None, None, None
                except Exception as e:
                    _LOGGER.error(f"WebSocket: Error receiving auth_required: {e}")
                    return None, None, None

                _LOGGER.debug(f"WS received: {msg.get('type')}")
                if msg.get("type") != "auth_required":
                    _LOGGER.error(f"WebSocket Protocol Error: Expected auth_required, got {msg}")
                    _LOGGER.debug(f"WebSocket: Full auth_required message: {msg}")
                    return None, None, None

                # 2. Send auth
                _LOGGER.debug("WebSocket: Sending auth token.")
                await ws.send_json({"type": "auth", "access_token": HA_TOKEN})
                
                # 3. Wait for auth_ok
                try:
                    auth_resp = await asyncio.wait_for(ws.receive_json(), timeout=5.0)
                except asyncio.TimeoutError:
                    _LOGGER.error("WebSocket: Timeout waiting for auth_ok message.")
                    return None, None, None
                except Exception as e:
                    _LOGGER.error(f"WebSocket: Error receiving auth_ok: {e}")
                    return None, None, None

                _LOGGER.debug(f"WebSocket: Auth response: {auth_resp}") # Log full response for debugging
                if auth_resp.get("type") != "auth_ok":
                    _LOGGER.error(f"WebSocket: Auth Failed: Expected 'auth_ok', got {auth_resp}")
                    return None, None, None

                _LOGGER.info("WebSocket: Authentication successful. Fetching registries.")

                # 4. Fetch registries
                async def ws_call(msg_id, msg_type):
                    _LOGGER.debug(f"WebSocket: Requesting {msg_type} with ID {msg_id}")
                    await ws.send_json({"id": msg_id, "type": msg_type})
                    while not ws.closed: # Check if connection is still open
                        try:
                            resp = await asyncio.wait_for(ws.receive_json(), timeout=10.0) # Add timeout for each response
                            if resp.get("id") == msg_id:
                                _LOGGER.debug(f"WebSocket: Received response for {msg_type} (ID {msg_id})")
                                return resp.get("result", [])
                            elif resp.get("type") == "event": # Ignore events
                                continue
                            else:
                                _LOGGER.warning(f"WebSocket: Received unexpected message (ID: {resp.get('id')}, Type: {resp.get('type')}) while waiting for {msg_type} (ID {msg_id}).")
                        except asyncio.TimeoutError:
                            _LOGGER.error(f"WebSocket: Timeout waiting for response for {msg_type} (ID {msg_id}).")
                            break # Break loop on timeout
                        except aiohttp.client_exceptions.ClientConnectionError as e:
                            _LOGGER.error(f"WebSocket: Connection error while waiting for {msg_type} (ID {msg_id}): {e}")
                            break # Break loop on connection error
                        except Exception as e:
                            _LOGGER.error(f"WebSocket: General error receiving response for {msg_type} (ID {msg_id}): {e}")
                            break # Break loop on general error
                    _LOGGER.warning(f"WebSocket: Connection closed or error before receiving response for {msg_type} (ID {msg_id}).")
                    return [] # Return empty list if connection closes or error occurs

                devs = await ws_call(1, "config/device_registry/list") # Use unique IDs for each request
                areas = await ws_call(2, "config/area_registry/list")
                ents = await ws_call(3, "config/entity_registry/list")
                
                _LOGGER.info("WebSocket: All registries fetched.")
                return devs, areas, ents
    except aiohttp.client_exceptions.WSServerHandshakeError as e:
        _LOGGER.error(f"WebSocket: Server Handshake Error: {e}. This often means the WS URL is incorrect or the server is not responding.")
        return None, None, None
    except Exception as e:
        _LOGGER.error(f"WebSocket: General Registry Fetch Error: {e}")
    return None, None, None

async def delete_warranty_api(request):
    """Delete a warranty entry."""
    try:
        device_id = request.match_info.get('device_id')
        current_data = load_warranty_data() or {} # Ensure current_data is always a dict
        if device_id in current_data:
            del current_data[device_id]
            save_warranty_data(current_data)
        return web.json_response({"status": "deleted"})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

# --- UI HANDLERS ---
async def handle_index(request):
    """Serve the Installer UI."""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>ClearSky Installer UI</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>body{font-family:sans-serif;padding:20px;background:#f4f4f4;color:#333}.card{background:#fff;padding:20px;border-radius:8px;box-shadow:0 2px 5px rgba(0,0,0,.1);max-width:600px;margin:20px auto}label{display:block;margin-top:15px;margin-bottom:5px;font-weight:700}select,input[type=date],button{width:100%;padding:10px;margin-bottom:10px;border:1px solid #ddd;border-radius:4px;box-sizing:border-box;font-size:16px}button{background:#03a9f4;color:#fff;border:none;cursor:pointer}h2{color:#444;text-align:center}#status{text-align:center;margin-top:20px;font-weight:700}.warranty-list{margin-top:30px}.area-group{margin-bottom:15px;border-bottom:1px solid #eee;padding-bottom:10px}.area-name{font-weight:700;background:#eee;padding:5px 10px;border-radius:4px}.device-item{display:flex;justify-content:space-between;align-items:center;padding:8px 10px;font-size:14px}.expired{color:red;font-weight:700}.btn-sm{width:auto;padding:5px 10px;margin-left:5px;font-size:12px;display:inline-block}</style>
        <style>details{margin-bottom:10px;background:#fff;border-radius:4px;overflow:hidden;border:1px solid #ddd}summary{padding:10px;background:#eee;font-weight:700;cursor:pointer;outline:none}</style>
    </head>
    <body>
        <div class="card">
            <div id="azureBanner" style="padding:10px 14px;border-radius:6px;margin-bottom:15px;font-size:13px;display:flex;align-items:center;justify-content:space-between;background:#e1f5fe;color:#0277bd;border:1px solid #b3e5fc">
                <div>☁️ <strong>Azure Sync:</strong> <span id="azureStatus">Checking...</span></div>
                <button type="button" class="btn-sm" onclick="checkStatus()" style="background:#0288d1;width:auto">Refresh</button>
            </div>
            <h2>Warranty Configuration</h2>
            <label>Select Area:</label>
            <select id="areaSelect" onchange="updateDeviceList()"><option value="">Loading...</option></select>
            <label>Select Device:</label>
            <select id="deviceSelect" onchange="loadExistingWarranty()"><option value="">-- Select Area First --</option></select>
            <label>Warranty State:</label>
            <select id="state" onchange="toggleDate()"><option value="Active">Active</option><option value="Monitored" selected>Monitored</option></select>
            <label>Expiry Date:</label>
            <input type="date" id="expiry">
            <button onclick="saveWarranty()">Save Warranty Info</button>
            <p id="status"></p>

            <div class="warranty-list" id="warrantyList"></div>
        </div>
        <script>
            let devices = [], areas = [], warranties = {};
            function toggleDate() { document.getElementById('expiry').disabled = document.getElementById('state').value === 'Monitored'; }
            async function load() {
                try {
                    const res = await fetch('./api/registry');
                    const data = await res.json();
                    devices = data.devices; areas = data.areas; warranties = data.warranties;
                    // Sort areas alphabetically
                    const aSel = document.getElementById('areaSelect');
                    areas.sort((a, b) => a.name.localeCompare(b.name));
                    aSel.innerHTML = '<option value="">-- All Areas --</option>' + areas.map(a => `<option value="${a.id}">${a.name}</option>`).join('');
                    updateDeviceList(); renderList();
                } catch (e) {
                    document.getElementById('status').innerText = 'Error loading data.';
                }
            }
            function updateDeviceList() {
                const aId = document.getElementById('areaSelect').value;
                const dSel = document.getElementById('deviceSelect');
                const filtered = aId ? devices.filter(d => d.area_id === aId) : devices;
                // Sort devices alphabetically
                filtered.sort((a, b) => a.name.localeCompare(b.name));
                dSel.innerHTML = '<option value="">-- Select Device --</option>' + filtered.map(d => `<option value="${d.id}">${d.name || d.id}</option>`).join(''); // Fallback to ID if name is missing
                loadExistingWarranty(); // Load warranty for the first device in the list or clear fields
            }
            function loadExistingWarranty() {
                const id = document.getElementById('deviceSelect').value;
                const w = warranties[id] || {};
                document.getElementById('state').value = w.warranty_state || 'Monitored';
                document.getElementById('expiry').value = w.expiry_date || ''; // Keep existing date if available
                toggleDate();
            }
            function renderList() {
                const list = document.getElementById('warrantyList');
                let html = '<h3>Saved Warranties</h3>';
                const grouped = {};
                Object.keys(warranties).forEach(id => {
                    const dev = devices.find(d => d.id === id) || {name: 'Unknown', area_id: null};
                    const area = areas.find(a => a.id === dev.area_id) || {name: 'No Area'};
                    if (!grouped[area.name]) {
                        grouped[area.name] = [];
                    }
                    grouped[area.name].push({id, name: dev.name, ...warranties[id]});
                });
                for (const area in grouped) {
                    html += `<details open><summary>${area} (${grouped[area].length})</summary>`;
                    grouped[area].forEach(w => {
                        let displayState = w.warranty_state;
                        const isExp = w.expiry_date && new Date(w.expiry_date) < new Date().setHours(0,0,0,0);
                        if (displayState === 'Active' && isExp) displayState = 'Expired';
                        html += `<div class="device-item">
                            <span>${w.name} - <span class="${displayState==='Expired'?'expired':''}">${displayState}</span> (${w.expiry_date || 'N/A'})</span>
                            <div>
                                <button class="btn-sm" onclick="editWar('${w.id}')">✏️</button>
                                <button class="btn-sm" style="background:#f44336" onclick="deleteWar('${w.id}')">🗑️</button>
                            </div>
                        </div>`;
                    });
                    html += `</details>`;
                }
                list.innerHTML = html;
            }
            async function editWar(id) {
                const dev = devices.find(d => d.id === id);
                if (dev) {
                    document.getElementById('areaSelect').value = dev.area_id || "";
                    updateDeviceList();
                    document.getElementById('deviceSelect').value = id;
                    loadExistingWarranty();
                    window.scrollTo(0,0);
                }
            }
            async function deleteWar(id) {
                if (confirm('Delete this warranty info?')) {
                    await fetch(`./api/warranty/${id}`, {method: 'DELETE'});
                    load();
                }
            }
            async function saveWarranty() {
                const id = document.getElementById('deviceSelect').value;
                if(!id) return alert('Select a device');
                const data = { device_id: id, warranty_state: document.getElementById('state').value, expiry_date: document.getElementById('expiry').value };
                const res = await fetch('./api/warranty', { method: 'POST', body: JSON.stringify(data), headers: {'Content-Type': 'application/json'} }); // Corrected 'currentWarranty[id] = data;' to 'load();'
                if(res.ok) { document.getElementById('status').innerText = 'Saved!'; load(); }
            }
            async function checkStatus() {
                try {
                    const res = await fetch('./api/status');
                    const data = await res.json();
                    const el = document.getElementById('azureStatus');
                    const banner = document.getElementById('azureBanner');
                    if (!data.azure.configured) {
                        el.innerText = 'Not Configured (Add connection string in addon options)';
                        banner.style.background = '#fff3e0';
                        banner.style.color = '#e65100';
                        banner.style.borderColor = '#ffe0b2';
                    } else if (data.azure.status.last_status === 'success') {
                        const time = data.azure.status.last_success ? new Date(data.azure.status.last_success).toLocaleTimeString() : 'Recent';
                        el.innerText = `Connected & Synced (${time})`;
                        banner.style.background = '#e8f5e9';
                        banner.style.color = '#2e7d32';
                        banner.style.borderColor = '#c8e6c9';
                    } else if (data.azure.status.last_status === 'failed') {
                        el.innerText = `Sync Failed: ${data.azure.status.last_error || 'Error'}`;
                        banner.style.background = '#ffebee';
                        banner.style.color = '#c62828';
                        banner.style.borderColor = '#ffcdd2';
                    } else {
                        el.innerText = `Configured (${data.azure.status.last_status})`;
                    }
                } catch (e) {
                    document.getElementById('azureStatus').innerText = 'Status check failed';
                }
            }
            load(); toggleDate(); checkStatus();
        </script>
    </body>
    </html>
    """
    return web.Response(text=html, content_type='text/html')

async def get_registry_api(request):
    """API to feed the UI registry and warranty data."""
    devices, areas, entities = await _get_ha_registries()
    warranties = load_warranty_data()
    return web.json_response({
        "devices": [{"id": d["id"], "name": d.get("name_by_user") or d.get("name") or d["id"], "area_id": d.get("area_id")} for d in (devices or [])],
        "areas": [{"id": a["area_id"], "name": a["name"]} for a in (areas or [])],
        "warranties": warranties
    })

async def get_warranty_api(request):
    return web.json_response(load_warranty_data())

async def save_warranty_api(request):
    new_entry = await request.json()
    current_data = load_warranty_data()
    current_data[new_entry['device_id']] = {
        "warranty_state": new_entry['warranty_state'],
        "expiry_date": new_entry['expiry_date'],
        "updated_at": datetime.now().isoformat()
    }
    save_warranty_data(current_data)
    return web.json_response({"status": "ok"})

async def get_status_api(request):
    """API returning system health and upload status."""
    config = load_addon_config()
    conn_configured = bool(config.get("azure_storage_connection_string"))
    platform_configured = bool(config.get("platform_api_url") and config.get("registration_token"))
    return web.json_response({
        "version": "0.3.0",
        "poll_interval": config.get("poll_interval", 90),
        "instance_uuid": get_or_create_instance_uuid(),
        "azure": {
            "upload_enabled": config.get("azure_upload_enabled", True),
            "configured": conn_configured,
            "container_name": config.get("azure_container_name", "clearsky-snapshots"),
            "sdk_available": AZURE_SDK_AVAILABLE,
            "status": azure_upload_status
        },
        "platform": {
            "enabled": config.get("platform_enabled", False),
            "configured": platform_configured,
            "api_url": config.get("platform_api_url", ""),
            "instance_name": config.get("instance_name", "My Home"),
            "status": platform_upload_status
        },
        "server_time": datetime.now().astimezone().isoformat()
    })

async def fetch_full_snapshot():
    """
    Fetch required data via REST API.
    Returns a dictionary containing the complete snapshot.
    """
    if not HA_TOKEN:
        _LOGGER.error("SUPERVISOR_TOKEN is missing from environment variables.")
        return None

    headers = {
        "Authorization": f"Bearer {HA_TOKEN}",
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
    }

    async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as session:
        async def fetch(endpoint):
            url = f"{HA_URL}/{endpoint}"
            async with session.get(url) as resp:
                if resp.status != 200:
                    _LOGGER.warning(f"Failed to fetch {endpoint}: HTTP {resp.status}")
                    return None
                return await resp.json()

        results = await asyncio.gather(
            fetch("states"),
            _get_ha_registries(),
            return_exceptions=True
        )
        
        states = results[0] if not isinstance(results[0], Exception) else None
        dev_reg, area_reg, ent_reg = results[1] if not isinstance(results[1], Exception) else (None, None, None)

    if states is None or dev_reg is None:
        _LOGGER.error("Incomplete snapshot data. Skipping.")
        return None

    warranties = load_warranty_data()
    area_map = {a['area_id']: a['name'] for a in area_reg}
    state_map = {s['entity_id']: s for s in states}
    today = datetime.now().date()
    
    enriched_devices = []
    for d in dev_reg:
        d_id = d['id']
        dev_entities = [e for e in ent_reg if e.get('device_id') == d_id]

        w_info = warranties.get(d_id)
        warranty_details = None

        if w_info:
            display_state = w_info.get("warranty_state", "Monitored")
            expiry_str = w_info.get("expiry_date")
            
            # Logic to automatically compute "Expired" status for the snapshot
            if display_state == "Active" and expiry_str:
                try:
                    # HTML5 date picker format is YYYY-MM-DD
                    exp_date = datetime.strptime(expiry_str, "%Y-%m-%d").date()
                    if exp_date < today:
                        display_state = "Expired"
                except (ValueError, TypeError):
                    pass

            warranty_details = {
                "warranty_state": display_state,
                "expiry_date": expiry_str or "N/A",
                "updated_at": w_info.get("updated_at", "N/A")
            }

        enriched_devices.append({
            "id": d_id,
            "name": d.get("name_by_user") or d.get("name"),
            "area": area_map.get(d.get("area_id"), "No Area"),
            "warranty_details": warranty_details,
            "entities_data": [ # This section contains the state and attributes for each entity, which can indicate device modes or failure states.
                {
                    "entity_id": e['entity_id'], 
                    "state": state_map.get(e['entity_id'], {}).get('state'), 
                    "attributes": state_map.get(e['entity_id'], {}).get('attributes'),
                    "last_reported": state_map.get(e['entity_id'], {}).get('last_reported')
                }
                for e in dev_entities if e['entity_id'] in state_map
            ]
        })

    return {
        "timestamp": datetime.now().astimezone().isoformat(),
        "devices": enriched_devices
    }
def _write_snapshot_sync(snapshot: dict) -> None:
    """Actual synchronous write logic with rotation (max 10 files)."""
    max_files = 10
    output_dir = "/config/clearsky_snapshots"  # This correctly targets the data folder
    os.makedirs(output_dir, exist_ok=True)
    base_path = os.path.join(output_dir, "clearsky_snapshot")
    
    # 1. Identify current files or empty slots
    target_path = None
    for i in range(1, max_files + 1):
        fpath = f"{base_path}_{i}.json"
        if not os.path.exists(fpath):
            target_path = fpath
            break
    
    # 2. If all slots are full, find the oldest
    if not target_path:
        slots = [f"{base_path}_{i}.json" for i in range(1, max_files + 1)]
        target_path = min(slots, key=os.path.getmtime)

    temp_path = f"{target_path}.tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())  # Force write to physical storage
        os.replace(temp_path, target_path)
        _LOGGER.info(f"Snapshot written to {target_path} (Device Timestamp: {snapshot.get('timestamp')})")
    except Exception as e:
        _LOGGER.error(f"Failed to write snapshot to {target_path}: {e}")

async def write_snapshot_async(snapshot: dict) -> None:
    """Save snapshot JSON to persistent storage."""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _write_snapshot_sync, snapshot)

def _upload_to_azure_sync(snapshot: dict, config: dict) -> dict:
    """
    Upload snapshot to Azure Blob Storage using dual strategy:
    1. Overwrite 'latest.json' for quick web app queries
    2. Save timestamped snapshot 'snapshots/snapshot_{slug}.json' for historical archiving
    """
    if not AZURE_SDK_AVAILABLE:
        raise RuntimeError("azure-storage-blob library is not installed in the environment.")

    conn_str = config.get("azure_storage_connection_string")
    container_name = config.get("azure_container_name", "clearsky-snapshots")

    if not conn_str:
        raise ValueError("Azure Storage connection string is empty.")

    blob_service_client = BlobServiceClient.from_connection_string(conn_str)
    container_client = blob_service_client.get_container_client(container_name)

    # Ensure container exists
    try:
        container_client.create_container()
        _LOGGER.info(f"Created Azure container '{container_name}'")
    except Exception:
        # Container already exists or permission only permits write
        pass

    json_str = json.dumps(snapshot, indent=2, ensure_ascii=False)
    json_bytes = json_str.encode("utf-8")

    content_settings = ContentSettings(
        content_type="application/json; charset=utf-8",
        cache_control="no-cache, no-store"
    )

    metadata = {
        "device_count": str(len(snapshot.get("devices", []))),
        "snapshot_timestamp": str(snapshot.get("timestamp", ""))
    }

    # 1. Overwrite latest.json for web app consumption
    latest_blob = container_client.get_blob_client("latest.json")
    latest_blob.upload_blob(
        json_bytes,
        overwrite=True,
        content_settings=content_settings,
        metadata=metadata
    )

    # 2. Upload timestamped historical snapshot
    ts_raw = snapshot.get("timestamp", "")
    slug = "".join(c for c in ts_raw.split(".")[0] if c.isdigit())
    if not slug:
        slug = datetime.now().strftime("%Y%m%d_%H%M%S")
    history_blob_name = f"snapshots/snapshot_{slug}.json"

    history_blob = container_client.get_blob_client(history_blob_name)
    history_blob.upload_blob(
        json_bytes,
        overwrite=True,
        content_settings=ContentSettings(content_type="application/json; charset=utf-8"),
        metadata=metadata
    )

    return {
        "container": container_name,
        "latest_blob": "latest.json",
        "history_blob": history_blob_name,
        "size_bytes": len(json_bytes)
    }

async def upload_to_azure_async(snapshot: dict, config: dict) -> None:
    """Asynchronously execute Azure upload without blocking the main event loop."""
    global azure_upload_status
    loop = asyncio.get_running_loop()
    azure_upload_status["last_attempt"] = datetime.now().astimezone().isoformat()
    try:
        res = await loop.run_in_executor(None, _upload_to_azure_sync, snapshot, config)
        azure_upload_status["last_status"] = "success"
        azure_upload_status["last_success"] = datetime.now().astimezone().isoformat()
        azure_upload_status["last_error"] = None
        azure_upload_status["blobs_written"] = [res["latest_blob"], res["history_blob"]]
        _LOGGER.info(
            f"Successfully uploaded snapshot to Azure: {res['latest_blob']} & {res['history_blob']} "
            f"({res['size_bytes']} bytes) in container '{res['container']}'"
        )
    except Exception as e:
        azure_upload_status["last_status"] = "failed"
        azure_upload_status["last_error"] = str(e)
        _LOGGER.error(f"Failed to upload snapshot to Azure Storage: {e}")

# Platform Registration (Phase 1)
INSTANCE_UUID_PATH = "/data/instance_uuid.json"

def get_or_create_instance_uuid():
    """Get existing instance UUID or create a new one."""
    if os.path.exists(INSTANCE_UUID_PATH):
        try:
            with open(INSTANCE_UUID_PATH, "r") as f:
                data = json.load(f)
                return data.get("instance_uuid")
        except Exception as e:
            _LOGGER.error(f"Error loading instance UUID: {e}")
    
    # Create new UUID
    import uuid
    instance_uuid = str(uuid.uuid4())
    try:
        with open(INSTANCE_UUID_PATH, "w") as f:
            json.dump({"instance_uuid": instance_uuid}, f)
        _LOGGER.info(f"Created new instance UUID: {instance_uuid}")
    except Exception as e:
        _LOGGER.error(f"Error saving instance UUID: {e}")
    
    return instance_uuid

async def register_with_platform(config: dict) -> dict:
    """Register this instance with the ClearSky Platform."""
    registration_token = config.get("registration_token", "").strip()
    instance_name = config.get("instance_name", "My Home")
    platform_api_url = config.get("platform_api_url", "").strip()
    
    if not registration_token or not platform_api_url:
        _LOGGER.warning("Platform registration skipped: registration_token or platform_api_url not set")
        return None
    
    instance_uuid = get_or_create_instance_uuid()
    
    try:
        async with aiohttp.ClientSession() as session:
            url = f"{platform_api_url.rstrip('/')}/api/instances/register"
            payload = {
                "registration_token": registration_token,
                "instance_uuid": instance_uuid,
                "instance_name": instance_name,
                "ha_version": os.getenv("HOMEASSISTANT_VERSION", "unknown")
            }
            
            _LOGGER.info(f"Registering instance with platform: {url}")
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status == 200:
                    data = await response.json()
                    _LOGGER.info(f"Successfully registered instance: {data.get('instance_id')}")
                    return data
                else:
                    error_text = await response.text()
                    _LOGGER.error(f"Platform registration failed: {response.status} - {error_text}")
                    return None
    except Exception as e:
        _LOGGER.error(f"Error during platform registration: {e}")
        return None

async def upload_to_platform(snapshot: dict, config: dict) -> None:
    """Upload snapshot to ClearSky Platform."""
    if not config.get("platform_enabled"):
        return
    
    platform_api_url = config.get("platform_api_url", "").strip()
    if not platform_api_url:
        return
    
    instance_uuid = get_or_create_instance_uuid()
    
    try:
        async with aiohttp.ClientSession() as session:
            url = f"{platform_api_url.rstrip('/')}/api/instances/{instance_uuid}/snapshot"
            
            _LOGGER.debug(f"Uploading snapshot to platform: {url}")
            async with session.post(url, json=snapshot, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status == 200:
                    _LOGGER.debug("Successfully uploaded snapshot to platform")
                else:
                    error_text = await response.text()
                    _LOGGER.warning(f"Platform upload failed: {response.status} - {error_text}")
    except Exception as e:
        _LOGGER.error(f"Error during platform upload: {e}")

def handle_sigterm(signum, frame):
    """Graceful shutdown handler for Docker stop signals."""
    _LOGGER.info("Received SIGTERM – shutting down.")
    shutdown_event.set()

async def background_tasks(app):
    """Manage the snapshot loop task within the web server context."""
    _LOGGER.info("Starting background snapshot task...")
    task = asyncio.create_task(main_loop())
    yield
    _LOGGER.info("Stopping background snapshot task...")
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

async def main_loop():
    """Run forever, polling and saving snapshots every configured poll interval."""
    _LOGGER.info("ClearSky agent snapshot loop started.")

    # Register with platform on startup if enabled
    config = load_addon_config()
    if config.get("platform_enabled"):
        registration_result = await register_with_platform(config)
        if registration_result:
            platform_upload_status["registered"] = True
            platform_upload_status["instance_id"] = registration_result.get("instance_id")
            platform_upload_status["last_status"] = "registered"

    while not shutdown_event.is_set():
        config = load_addon_config()
        poll_interval = config.get("poll_interval", 90)

        if not HA_TOKEN:
            _LOGGER.error("SUPERVISOR_TOKEN not set. Waiting 30s...")
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=30)
                break
            except asyncio.TimeoutError:
                continue

        try:
            snapshot = await fetch_full_snapshot()
            if snapshot:
                # 1. Local rotated write
                await write_snapshot_async(snapshot)

                # 2. Azure Storage upload (legacy)
                if config.get("azure_upload_enabled"):
                    if config.get("azure_storage_connection_string"):
                        await upload_to_azure_async(snapshot, config)
                    else:
                        azure_upload_status["last_status"] = "unconfigured"
                        _LOGGER.debug("Azure upload skipped: Connection string not set in options.")
                else:
                    azure_upload_status["last_status"] = "disabled"

                # 3. Platform upload (Phase 1)
                if config.get("platform_enabled"):
                    platform_upload_status["last_attempt"] = datetime.now().astimezone().isoformat()
                    try:
                        await upload_to_platform(snapshot, config)
                        platform_upload_status["last_status"] = "success"
                        platform_upload_status["last_success"] = datetime.now().astimezone().isoformat()
                        platform_upload_status["last_error"] = None
                    except Exception as e:
                        platform_upload_status["last_status"] = "failed"
                        platform_upload_status["last_error"] = str(e)
                        _LOGGER.error(f"Platform upload failed: {e}")
                else:
                    platform_upload_status["last_status"] = "disabled"
        except asyncio.TimeoutError:
            _LOGGER.warning("API request timed out – will retry")
        except Exception as e:
            _LOGGER.error(f"Error during snapshot: {e}")

        # Wait before next poll or until shutdown
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=poll_interval)
        except asyncio.TimeoutError:
            continue

def main():
    # Register signal handler for clean exit
    signal.signal(signal.SIGTERM, handle_sigterm)
    
    app = web.Application()
    app.cleanup_ctx.append(background_tasks)
    
    app.router.add_get('/', handle_index)
    app.router.add_get('/api/status', get_status_api)
    app.router.add_get('/api/registry', get_registry_api)
    app.router.add_get('/api/warranty', get_warranty_api)
    app.router.add_post('/api/warranty', save_warranty_api)
    app.router.add_delete('/api/warranty/{device_id}', delete_warranty_api)
    
    _LOGGER.info("Starting Ingress server on port 8099...")
    web.run_app(app, port=8099, handle_signals=True)

if __name__ == "__main__":
    main()