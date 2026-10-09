# Phase 1 Azure Infrastructure Setup

## Required Azure Resources

### 1. Azure Functions (Backend API)
- **Resource Type**: Function App
- **Runtime**: Python 3.11
- **Hosting Plan**: Consumption (serverless)
- **Region**: Choose region closest to users
- **Storage Account**: Required for Functions

### 2. Azure Cosmos DB (Serverless)
- **Resource Type**: Azure Cosmos DB Account
- **API**: SQL (Core)
- **Capacity Mode**: Serverless
- **Region**: Same region as Functions
- **Consistency**: Session (default)

### 3. Azure Blob Storage
- **Resource Type**: Storage Account (V2)
- **Tier**: Standard
- **Access Tier**: Hot
- **Redundancy**: LRS (Locally Redundant Storage) for MVP

### 4. Azure AD (Entra ID)
- **Resource Type**: Azure Active Directory
- **Features**: User authentication, JWT tokens
- **App Registration**: Need to register the web app and functions

### 5. Azure Static Web Apps (Web Dashboard)
- **Resource Type**: Static Web App
- **Runtime**: JavaScript/React
- **Branch**: main
- **Build**: GitHub Actions auto-deploy

## Cosmos DB Setup

### Create Database and Containers

1. In Azure Portal, go to your Cosmos DB account
2. Create a new database named `clearsky-platform`
3. Create three containers:

#### Users Container
- **Container name**: `users`
- **Partition key**: `/id`
- **Throughput**: Serverless (auto-scale)

#### Instances Container
- **Container name**: `instances`
- **Partition key**: `/id`
- **Throughput**: Serverless (auto-scale)

#### Instance Access Container
- **Container name**: `instance_access`
- **Partition key**: `/id`
- **Throughput**: Serverless (auto-scale)

### Document Structures

**Users Document:**
```json
{
  "id": "uuid",
  "azure_ad_id": "azure_ad_id_or_null",
  "email": "user@example.com",
  "user_type": "end_user|installer|admin",
  "created_at": "2026-10-09T12:00:00Z"
}
```

**Instances Document:**
```json
{
  "id": "uuid",
  "instance_uuid": "unique_instance_id",
  "owner_id": "user_uuid",
  "instance_name": "My Home",
  "storage_container": "instances/{instance_uuid}",
  "ha_version": "2024.1.0",
  "last_sync": "2026-10-09T12:00:00Z",
  "created_at": "2026-10-09T12:00:00Z"
}
```

**Instance Access Document:**
```json
{
  "id": "uuid",
  "instance_id": "instance_uuid",
  "user_id": "user_uuid",
  "access_level": "viewer|full_access",
  "created_at": "2026-10-09T12:00:00Z"
}
```

## API Endpoints

### Authentication
- `POST /api/auth/login` - Azure AD login, returns JWT (future)

### User Management
- `POST /api/users/register` - Register new user (end user or installer)
- `GET /api/users/me` - Get current user info (future)

### Instance Management
- `POST /api/instances/register` - Register HAOS instance (from add-on)
- `GET /api/instances` - List accessible instances
- `GET /api/instances/{id}` - Get instance details (future)

### Data Access
- `GET /api/instances/{id}/snapshot/latest` - Get latest snapshot
- `GET /api/instances/{id}/snapshots` - List historical snapshots (future)
- `GET /api/instances/{id}/snapshots/{snapshot_id}` - Get specific snapshot (future)

## Environment Variables

### Azure Functions
```
COSMOS_DB_CONNECTION_STRING=<cosmos_db_connection_string>
AZURE_BLOB_CONNECTION_STRING=<blob_connection_string>
AZURE_AD_TENANT_ID=<tenant_id>
AZURE_AD_CLIENT_ID=<client_id>
AZURE_AD_CLIENT_SECRET=<client_secret>
JWT_SECRET=<secret_for_jwt_signing>
API_BASE_URL=https://your-functions-app.azurewebsites.net
```

### HAOS Add-on
```
clearsky_platform:
  platform_enabled: true
  platform_api_url: "https://your-functions-app.azurewebsites.net"
  registration_token: ""  # Obtained from user registration
  instance_name: "My Home"
```

## Storage Organization

```
clearsky-platform/
├── instances/
│   ├── {instance_uuid_1}/
│   │   ├── latest.json
│   │   └── snapshots/
│   │       ├── snapshot_20261009_120000.json
│   │       └── snapshot_20261009_123000.json
│   └── {instance_uuid_2}/
│       ├── latest.json
│       └── snapshots/
```

## Cost Estimate (MVP - Optimized)

- Azure Functions (Consumption): ~$0-2/month
- Azure Cosmos DB (Serverless): ~$0.02/month (pay per request)
- Azure Blob Storage: ~$0.51/month (Hot + Cool tiers)
- Azure Static Web Apps: Free tier
- Azure AD: Free tier

**Total: ~$2.53/month for MVP**

**First 12 months: $0** (using Azure free tiers)

### Cost Breakdown by Scale

| Users | Instances | Monthly Cost |
|-------|-----------|--------------|
| 1     | 1-2       | $0-2.53      |
| 10    | 10-20     | $5-10        |
| 50    | 50-100    | $20-30       |
| 100   | 100-200   | $40-50       |

### When to Scale

When Cosmos DB Serverless costs reach ~$50-100/month:
- Migrate to Provisioned Throughput (no code changes)
- Set fixed RU/s (e.g., 400 RU/s)
- More cost-effective at scale

## Setup Order

1. Create Resource Group
2. Create Storage Account (for Functions + Blobs)
3. Create Azure Cosmos DB Account (Serverless)
4. Create Cosmos DB database and containers
5. Create Azure Functions App
6. Configure Azure AD App Registration (future)
7. Create Static Web App
8. Deploy Functions code
9. Deploy web app
10. Test end-to-end

## Cost Optimization Tips

1. **Use Azure Free Tiers** (first 12 months):
   - $200 credit for first 30 days
   - Free Functions (1M requests)
   - Free Blob Storage (5GB)
   - Free Cosmos DB (limited)

2. **Implement Snapshot Compression**:
   - gzip compression reduces storage by ~70%
   - Reduces costs from $0.51 to ~$0.15/month

3. **Use Hot/Cool Storage Tiers**:
   - Keep 7 days in Hot, rest in Cool
   - Reduces storage costs by ~35%

4. **Archive Old Snapshots**:
   - Move >30 days to Archive tier
   - Further cost reduction
