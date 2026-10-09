# Phase 1 Azure Infrastructure Setup

## Required Azure Resources

### 1. Azure Functions (Backend API)
- **Resource Type**: Function App
- **Runtime**: Python 3.11
- **Hosting Plan**: Consumption (serverless)
- **Region**: Choose region closest to users
- **Storage Account**: Required for Functions

### 2. Azure SQL Database
- **Resource Type**: SQL Database
- **Tier**: Basic (for MVP)
- **Compute**: Serverless (auto-pause when not in use)
- **Backup**: Point-in-time restore enabled

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

## Database Schema

```sql
-- Users Table
CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT (NEWID()),
  azure_ad_id VARCHAR(255) UNIQUE,
  email VARCHAR(255),
  user_type VARCHAR(50) CHECK (user_type IN ('end_user', 'installer', 'admin')),
  created_at DATETIME2 DEFAULT GETDATE()
);

-- Instances Table
CREATE TABLE instances (
  id UUID PRIMARY KEY DEFAULT (NEWID()),
  instance_uuid VARCHAR(255) UNIQUE,
  owner_id UUID NOT NULL,
  instance_name VARCHAR(255),
  storage_container VARCHAR(255),
  ha_version VARCHAR(50),
  last_sync DATETIME2,
  created_at DATETIME2 DEFAULT GETDATE(),
  FOREIGN KEY (owner_id) REFERENCES users(id)
);

-- Instance Access Table
CREATE TABLE instance_access (
  id UUID PRIMARY KEY DEFAULT (NEWID()),
  instance_id UUID NOT NULL,
  user_id UUID NOT NULL,
  access_level VARCHAR(50) CHECK (access_level IN ('viewer', 'full_access')),
  created_at DATETIME2 DEFAULT GETDATE(),
  FOREIGN KEY (instance_id) REFERENCES instances(id),
  FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Indexes for performance
CREATE INDEX idx_instances_owner ON instances(owner_id);
CREATE INDEX idx_instance_access_instance ON instance_access(instance_id);
CREATE INDEX idx_instance_access_user ON instance_access(user_id);
```

## API Endpoints

### Authentication
- `POST /api/auth/login` - Azure AD login, returns JWT

### User Management
- `POST /api/users/register` - Register new user (end user or installer)
- `GET /api/users/me` - Get current user info

### Instance Management
- `POST /api/instances/register` - Register HAOS instance (from add-on)
- `GET /api/instances` - List accessible instances
- `GET /api/instances/{id}` - Get instance details

### Data Access
- `GET /api/instances/{id}/snapshot/latest` - Get latest snapshot
- `GET /api/instances/{id}/snapshots` - List historical snapshots
- `GET /api/instances/{id}/snapshots/{snapshot_id}` - Get specific snapshot

## Environment Variables

### Azure Functions
```
AZURE_SQL_CONNECTION_STRING=<sql_connection_string>
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
  api_base_url: "https://your-functions-app.azurewebsites.net"
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

## Cost Estimate (MVP)

- Azure Functions (Consumption): ~$0-5/month
- Azure SQL (Basic Serverless): ~$5-10/month
- Azure Blob Storage: ~$0-2/month
- Azure Static Web Apps: Free tier
- Azure AD: Free tier

**Total: ~$5-17/month for MVP**

## Setup Order

1. Create Resource Group
2. Create Storage Account (for Functions + Blobs)
3. Create Azure SQL Database
4. Create Azure Functions App
5. Configure Azure AD App Registration
6. Create Static Web App
7. Deploy database schema
8. Deploy Functions code
9. Deploy web app
10. Test end-to-end
