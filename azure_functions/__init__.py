import azure.functions as func
import logging
import json
import uuid
import os
from datetime import datetime
from azure.storage.blob import BlobServiceClient
from azure.cosmos import CosmosClient, PartitionKey
from python_jose import jwt
from passlib.context import CryptContext

app = func.FunctionApp()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Cosmos DB client
cosmos_client = None
database = None
users_container = None
instances_container = None
instance_access_container = None

def get_cosmos_client():
    global cosmos_client, database, users_container, instances_container, instance_access_container
    
    if cosmos_client is None:
        conn_str = os.environ.get("COSMOS_DB_CONNECTION_STRING")
        if not conn_str:
            raise ValueError("COSMOS_DB_CONNECTION_STRING not set")
        
        cosmos_client = CosmosClient.from_connection_string(conn_str)
        database = cosmos_client.get_database_client("clearsky-platform")
        
        users_container = database.get_container_client("users")
        instances_container = database.get_container_client("instances")
        instance_access_container = database.get_container_client("instance_access")
    
    return cosmos_client

# Blob storage client
def get_blob_client():
    conn_str = os.environ.get("AZURE_BLOB_CONNECTION_STRING")
    if not conn_str:
        raise ValueError("AZURE_BLOB_CONNECTION_STRING not set")
    return BlobServiceClient.from_connection_string(conn_str)

# JWT validation
def validate_jwt_token(token):
    try:
        secret = os.environ.get("JWT_SECRET")
        if not secret:
            raise ValueError("JWT_SECRET not set")
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        return payload
    except Exception as e:
        logger.error(f"JWT validation failed: {e}")
        return None

# Create user
@app.route(route="api/users/register", methods=["POST"])
def register_user(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body = req.get_json()
        email = body.get("email")
        user_type = body.get("user_type", "end_user")  # 'end_user' or 'installer'
        
        if not email:
            return func.HttpResponse(
                json.dumps({"error": "email is required"}),
                status_code=400,
                mimetype="application/json"
            )
        
        get_cosmos_client()
        
        user_id = str(uuid.uuid4())
        registration_token = str(uuid.uuid4())
        
        user_doc = {
            "id": user_id,
            "azure_ad_id": None,
            "email": email,
            "user_type": user_type,
            "created_at": datetime.now().isoformat()
        }
        
        users_container.create_item(body=user_doc)
        
        logger.info(f"Created user: {user_id} ({user_type})")
        
        return func.HttpResponse(
            json.dumps({
                "user_id": user_id,
                "registration_token": registration_token,
                "user_type": user_type
            }),
            status_code=200,
            mimetype="application/json"
        )
            
    except Exception as e:
        logger.error(f"Registration error: {e}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )

# Register instance (from HAOS add-on)
@app.route(route="api/instances/register", methods=["POST"])
def register_instance(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body = req.get_json()
        registration_token = body.get("registration_token")
        instance_uuid = body.get("instance_uuid")
        instance_name = body.get("instance_name", "My Home")
        ha_version = body.get("ha_version", "unknown")
        
        if not registration_token or not instance_uuid:
            return func.HttpResponse(
                json.dumps({"error": "registration_token and instance_uuid are required"}),
                status_code=400,
                mimetype="application/json"
            )
        
        get_cosmos_client()
        
        # Check if instance already exists
        query = "SELECT * FROM instances c WHERE c.instance_uuid = @instance_uuid"
        parameters = [{"name": "@instance_uuid", "value": instance_uuid}]
        
        existing = list(instances_container.query_items(
            query=query,
            parameters=parameters,
            enable_cross_partition_query=True
        ))
        
        if existing:
            instance_id = existing[0]["id"]
            storage_container = existing[0]["storage_container"]
            logger.info(f"Instance already registered: {instance_id}")
        else:
            instance_id = str(uuid.uuid4())
            storage_container = f"instances/{instance_uuid}"
            
            # Create user record if it doesn't exist (for MVP)
            owner_id = str(uuid.uuid4())
            user_doc = {
                "id": owner_id,
                "azure_ad_id": None,
                "email": f"user_{instance_uuid[:8]}",
                "user_type": "end_user",
                "created_at": datetime.now().isoformat()
            }
            users_container.create_item(body=user_doc)
            
            instance_doc = {
                "id": instance_id,
                "instance_uuid": instance_uuid,
                "owner_id": owner_id,
                "instance_name": instance_name,
                "storage_container": storage_container,
                "ha_version": ha_version,
                "last_sync": None,
                "created_at": datetime.now().isoformat()
            }
            instances_container.create_item(body=instance_doc)
            
            # Create container in Blob Storage
            blob_client = get_blob_client()
            container_client = blob_client.get_container_client(storage_container)
            container_client.create_container()
            
            logger.info(f"Registered new instance: {instance_id}")
        
        return func.HttpResponse(
            json.dumps({
                "instance_id": instance_id,
                "storage_container": storage_container,
                "api_key": registration_token  # For MVP, use same token
            }),
            status_code=200,
            mimetype="application/json"
        )
            
    except Exception as e:
        logger.error(f"Instance registration error: {e}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )

# Get instances (requires auth)
@app.route(route="api/instances", methods=["GET"])
def get_instances(req: func.HttpRequest) -> func.HttpResponse:
    # For MVP, skip auth - will add in production
    try:
        get_cosmos_client()
        
        query = "SELECT * FROM instances c ORDER BY c.created_at DESC"
        items = list(instances_container.query_items(
            query=query,
            enable_cross_partition_query=True
        ))
        
        instances = []
        for item in items:
            # Get owner email
            owner = users_container.read_item(item=item["owner_id"], partition_key=item["owner_id"])
            
            instances.append({
                "id": item["id"],
                "instance_uuid": item["instance_uuid"],
                "instance_name": item["instance_name"],
                "storage_container": item["storage_container"],
                "last_sync": item.get("last_sync"),
                "created_at": item["created_at"],
                "owner_email": owner.get("email") if owner else None
            })
        
        return func.HttpResponse(
            json.dumps({"instances": instances}),
            status_code=200,
            mimetype="application/json"
        )
        
    except Exception as e:
        logger.error(f"Get instances error: {e}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )

# Upload snapshot (from HAOS add-on)
@app.route(route="api/instances/{instance_uuid}/snapshot", methods=["POST"])
def upload_snapshot(req: func.HttpRequest) -> func.HttpResponse:
    try:
        instance_uuid = req.route_params.get("instance_uuid")
        snapshot_data = req.get_json()
        
        if not instance_uuid or not snapshot_data:
            return func.HttpResponse(
                json.dumps({"error": "instance_uuid and snapshot data are required"}),
                status_code=400,
                mimetype="application/json"
            )
        
        get_cosmos_client()
        
        # Get instance info
        query = "SELECT * FROM instances c WHERE c.instance_uuid = @instance_uuid"
        parameters = [{"name": "@instance_uuid", "value": instance_uuid}]
        
        items = list(instances_container.query_items(
            query=query,
            parameters=parameters,
            enable_cross_partition_query=True
        ))
        
        if not items:
            return func.HttpResponse(
                json.dumps({"error": "Instance not found"}),
                status_code=404,
                mimetype="application/json"
            )
        
        instance = items[0]
        storage_container = instance["storage_container"]
        
        # Upload to Blob Storage
        blob_client = get_blob_client()
        container_client = blob_client.get_container_client(storage_container)
        
        # Upload as latest.json
        blob_client_instance = container_client.get_blob_client("latest.json")
        blob_client_instance.upload_blob(
            json.dumps(snapshot_data),
            overwrite=True
        )
        
        # Also upload to snapshots folder with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        history_blob = f"snapshots/snapshot_{timestamp}.json"
        blob_client_history = container_client.get_blob_client(history_blob)
        blob_client_history.upload_blob(
            json.dumps(snapshot_data),
            overwrite=True
        )
        
        # Update last_sync in database
        instance["last_sync"] = datetime.now().isoformat()
        instances_container.replace_item(item=instance["id"], body=instance)
        
        logger.info(f"Uploaded snapshot for instance {instance_uuid}")
        
        return func.HttpResponse(
            json.dumps({"status": "success", "timestamp": timestamp}),
            status_code=200,
            mimetype="application/json"
        )
        
    except Exception as e:
        logger.error(f"Upload snapshot error: {e}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )

# Get latest snapshot
@app.route(route="api/instances/{instance_uuid}/snapshot/latest", methods=["GET"])
def get_latest_snapshot(req: func.HttpRequest) -> func.HttpResponse:
    try:
        instance_uuid = req.route_params.get("instance_uuid")
        
        get_cosmos_client()
        
        # Get instance info
        query = "SELECT * FROM instances c WHERE c.instance_uuid = @instance_uuid"
        parameters = [{"name": "@instance_uuid", "value": instance_uuid}]
        
        items = list(instances_container.query_items(
            query=query,
            parameters=parameters,
            enable_cross_partition_query=True
        ))
        
        if not items:
            return func.HttpResponse(
                json.dumps({"error": "Instance not found"}),
                status_code=404,
                mimetype="application/json"
            )
        
        storage_container = items[0]["storage_container"]
        
        # Download from Blob Storage
        blob_client = get_blob_client()
        container_client = blob_client.get_container_client(storage_container)
        blob_client_instance = container_client.get_blob_client("latest.json")
        
        download_stream = blob_client_instance.download_blob()
        data = json.loads(download_stream.readall())
        
        return func.HttpResponse(
            json.dumps(data),
            status_code=200,
            mimetype="application/json"
        )
        
    except Exception as e:
        logger.error(f"Get snapshot error: {e}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )
