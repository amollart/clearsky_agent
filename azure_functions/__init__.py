import azure.functions as func
import logging
import json
import uuid
import os
from datetime import datetime
from azure.storage.blob import BlobServiceClient
import pyodbc
from python_jose import jwt
from passlib.context import CryptContext

app = func.FunctionApp()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Database connection
def get_db_connection():
    conn_str = os.environ.get("AZURE_SQL_CONNECTION_STRING")
    if not conn_str:
        raise ValueError("AZURE_SQL_CONNECTION_STRING not set")
    return pyodbc.connect(conn_str)

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
        
        user_id = str(uuid.uuid4())
        registration_token = str(uuid.uuid4())
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT INTO users (id, email, user_type, created_at)
                VALUES (?, ?, ?, GETDATE())
            """, user_id, email, user_type)
            conn.commit()
            
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
            conn.rollback()
            logger.error(f"Database error: {e}")
            return func.HttpResponse(
                json.dumps({"error": str(e)}),
                status_code=500,
                mimetype="application/json"
            )
        finally:
            conn.close()
            
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
        
        # In a real implementation, validate the registration_token
        # For MVP, we'll accept any token and create the instance
        
        # Check if instance already exists
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT id FROM instances WHERE instance_uuid = ?
            """, instance_uuid)
            existing = cursor.fetchone()
            
            if existing:
                instance_id = existing[0]
                logger.info(f"Instance already registered: {instance_id}")
            else:
                instance_id = str(uuid.uuid4())
                storage_container = f"instances/{instance_uuid}"
                
                # Create user record if it doesn't exist (for MVP)
                # In production, this would be validated via registration_token
                owner_id = str(uuid.uuid4())
                cursor.execute("""
                    INSERT INTO users (id, email, user_type, created_at)
                    VALUES (?, ?, 'end_user', GETDATE())
                """, owner_id, f"user_{instance_uuid[:8]}")
                
                cursor.execute("""
                    INSERT INTO instances (id, instance_uuid, owner_id, instance_name, storage_container, ha_version, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, GETDATE())
                """, instance_id, instance_uuid, owner_id, instance_name, storage_container, ha_version)
                
                # Create container in Blob Storage
                blob_client = get_blob_client()
                container_client = blob_client.get_container_client(storage_container)
                container_client.create_container()
                
                conn.commit()
                logger.info(f"Registered new instance: {instance_id}")
            
            return func.HttpResponse(
                json.dumps({
                    "instance_id": instance_id,
                    "storage_container": f"instances/{instance_uuid}",
                    "api_key": registration_token  # For MVP, use same token
                }),
                status_code=200,
                mimetype="application/json"
            )
            
        except Exception as e:
            conn.rollback()
            logger.error(f"Database error: {e}")
            return func.HttpResponse(
                json.dumps({"error": str(e)}),
                status_code=500,
                mimetype="application/json"
            )
        finally:
            conn.close()
            
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
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT i.id, i.instance_uuid, i.instance_name, i.storage_container, i.last_sync, i.created_at,
                   u.email as owner_email
            FROM instances i
            LEFT JOIN users u ON i.owner_id = u.id
            ORDER BY i.created_at DESC
        """)
        
        instances = []
        for row in cursor.fetchall():
            instances.append({
                "id": row[0],
                "instance_uuid": row[1],
                "instance_name": row[2],
                "storage_container": row[3],
                "last_sync": str(row[4]) if row[4] else None,
                "created_at": str(row[5]) if row[5] else None,
                "owner_email": row[6]
            })
        
        conn.close()
        
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
        
        # Get instance info
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT storage_container FROM instances WHERE instance_uuid = ?
        """, instance_uuid)
        
        row = cursor.fetchone()
        if not row:
            conn.close()
            return func.HttpResponse(
                json.dumps({"error": "Instance not found"}),
                status_code=404,
                mimetype="application/json"
            )
        
        storage_container = row[0]
        conn.close()
        
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
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE instances SET last_sync = GETDATE() WHERE instance_uuid = ?
        """, instance_uuid)
        conn.commit()
        conn.close()
        
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
        
        # Get instance info
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT storage_container FROM instances WHERE instance_uuid = ?
        """, instance_uuid)
        
        row = cursor.fetchone()
        if not row:
            conn.close()
            return func.HttpResponse(
                json.dumps({"error": "Instance not found"}),
                status_code=404,
                mimetype="application/json"
            )
        
        storage_container = row[0]
        conn.close()
        
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
