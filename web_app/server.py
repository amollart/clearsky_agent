#!/usr/bin/env python3
"""
ClearSky Web App Server
Provides static hosting for the dashboard and an optional API proxy to Azure Blob Storage.
"""

import os
import sys
import json
import logging
from http.server import HTTPServer, SimpleHTTPRequestHandler
import urllib.parse
from datetime import datetime

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
_LOGGER = logging.getLogger("ClearSkyWebApp")

# Azure Storage SDK check
try:
    from azure.storage.blob import BlobServiceClient
    AZURE_SDK_AVAILABLE = True
except ImportError:
    BlobServiceClient = None
    AZURE_SDK_AVAILABLE = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SAMPLE_SNAPSHOT_PATH = os.path.join(BASE_DIR, "sample_snapshot.json")

def get_azure_client(conn_str=None):
    """Obtain BlobServiceClient from environment or supplied connection string."""
    if not AZURE_SDK_AVAILABLE:
        return None
    connection = conn_str or os.getenv("AZURE_STORAGE_CONNECTION_STRING", "").strip()
    if not connection:
        return None
    try:
        return BlobServiceClient.from_connection_string(connection)
    except Exception as e:
        _LOGGER.error(f"Failed to create Azure Blob Client: {e}")
        return None

class ClearSkyRequestHandler(SimpleHTTPRequestHandler):
    """Custom request handler that serves dashboard static files and Azure snapshot endpoints."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    def end_headers(self):
        # Enable CORS for development and cross-origin access
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization, x-azure-connection-string')
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def send_json(self, status_code: int, data: dict):
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2, ensure_ascii=False).encode('utf-8'))

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        # Health endpoint
        if path == "/api/health":
            conn_set = bool(os.getenv("AZURE_STORAGE_CONNECTION_STRING"))
            container_name = os.getenv("AZURE_CONTAINER_NAME", "clearsky-snapshots")
            self.send_json(200, {
                "service": "ClearSky Web Dashboard Server",
                "status": "healthy",
                "azure_sdk_available": AZURE_SDK_AVAILABLE,
                "azure_configured": conn_set,
                "container_name": container_name,
                "timestamp": datetime.now().astimezone().isoformat()
            })
            return

        # Fetch latest snapshot
        if path == "/api/snapshot/latest":
            self.handle_get_latest_snapshot(query)
            return

        # List snapshots in Azure container
        if path == "/api/snapshots":
            self.handle_list_snapshots(query)
            return

        # Fetch a specific snapshot by name
        if path.startswith("/api/snapshot/"):
            blob_name = urllib.parse.unquote(path[len("/api/snapshot/"):])
            self.handle_get_specific_snapshot(blob_name, query)
            return

        # Default static file serving (index.html, etc.)
        if path == "/":
            self.path = "/index.html"
        return super().do_GET()

    def handle_get_latest_snapshot(self, query):
        conn_override = self.headers.get("x-azure-connection-string") or (query.get("conn", [None])[0])
        container_name = os.getenv("AZURE_CONTAINER_NAME", "clearsky-snapshots")
        client = get_azure_client(conn_override)

        if client:
            try:
                container_client = client.get_container_client(container_name)
                blob_client = container_client.get_blob_client("latest.json")
                if blob_client.exists():
                    download_stream = blob_client.download_blob()
                    data = json.loads(download_stream.readall())
                    _LOGGER.info(f"Loaded 'latest.json' from Azure container '{container_name}'")
                    self.send_json(200, {
                        "source": "azure",
                        "container": container_name,
                        "blob": "latest.json",
                        "snapshot": data
                    })
                    return
                else:
                    _LOGGER.warning(f"'latest.json' not found in container '{container_name}'.")
            except Exception as e:
                _LOGGER.error(f"Error fetching latest.json from Azure: {e}")
                self.send_json(502, {"error": f"Azure fetch failed: {str(e)}", "fallback": "Using local sample"})
                return

        # Fallback to local sample snapshot if Azure is not configured or fails
        if os.path.exists(SAMPLE_SNAPSHOT_PATH):
            try:
                with open(SAMPLE_SNAPSHOT_PATH, "r", encoding="utf-8") as f:
                    sample_data = json.load(f)
                self.send_json(200, {
                    "source": "sample_fallback",
                    "note": "Azure connection not configured or 'latest.json' not yet uploaded. Displaying sample preview data.",
                    "snapshot": sample_data
                })
                return
            except Exception as e:
                self.send_json(500, {"error": f"Failed reading sample snapshot: {e}"})
                return

        self.send_json(404, {"error": "No snapshot available and sample snapshot missing."})

    def handle_list_snapshots(self, query):
        conn_override = self.headers.get("x-azure-connection-string") or (query.get("conn", [None])[0])
        container_name = os.getenv("AZURE_CONTAINER_NAME", "clearsky-snapshots")
        client = get_azure_client(conn_override)

        if not client:
            self.send_json(200, {
                "source": "sample",
                "blobs": [
                    {"name": "latest.json", "size": 3450, "last_modified": datetime.now().isoformat()},
                    {"name": "snapshots/sample_snapshot.json", "size": 3450, "last_modified": datetime.now().isoformat()}
                ]
            })
            return

        try:
            container_client = client.get_container_client(container_name)
            blobs = []
            for b in container_client.list_blobs():
                blobs.append({
                    "name": b.name,
                    "size": b.size,
                    "last_modified": b.last_modified.isoformat() if b.last_modified else None,
                    "content_type": b.content_settings.content_type if b.content_settings else "application/json"
                })
            # Sort newest first
            blobs.sort(key=lambda x: x["last_modified"] or "", reverse=True)
            self.send_json(200, {"container": container_name, "blobs": blobs})
        except Exception as e:
            self.send_json(500, {"error": f"Failed to list blobs: {e}"})

    def handle_get_specific_snapshot(self, blob_name, query):
        conn_override = self.headers.get("x-azure-connection-string") or (query.get("conn", [None])[0])
        container_name = os.getenv("AZURE_CONTAINER_NAME", "clearsky-snapshots")
        client = get_azure_client(conn_override)

        if not client:
            # Fallback if loading sample
            if blob_name in ("sample_snapshot.json", "snapshots/sample_snapshot.json") and os.path.exists(SAMPLE_SNAPSHOT_PATH):
                with open(SAMPLE_SNAPSHOT_PATH, "r", encoding="utf-8") as f:
                    self.send_json(200, {"source": "sample", "blob": blob_name, "snapshot": json.load(f)})
                return
            self.send_json(400, {"error": "Azure credentials not configured to fetch historical blob."})
            return

        try:
            container_client = client.get_container_client(container_name)
            blob_client = container_client.get_blob_client(blob_name)
            if not blob_client.exists():
                self.send_json(404, {"error": f"Blob '{blob_name}' not found."})
                return
            stream = blob_client.download_blob()
            data = json.loads(stream.readall())
            self.send_json(200, {"source": "azure", "blob": blob_name, "snapshot": data})
        except Exception as e:
            self.send_json(500, {"error": f"Error loading blob '{blob_name}': {e}"})

def run_server(port=8080):
    server_address = ('', port)
    httpd = HTTPServer(server_address, ClearSkyRequestHandler)
    _LOGGER.info(f"ClearSky Web Dashboard Server running at http://localhost:{port}/")
    _LOGGER.info(f"Azure SDK Available: {AZURE_SDK_AVAILABLE}")
    conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    if conn_str:
        _LOGGER.info("Azure connection string is set via environment variable.")
    else:
        _LOGGER.info("No Azure connection string set. Will use fallback preview data or UI settings.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        _LOGGER.info("Server stopped.")

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    run_server(port)

