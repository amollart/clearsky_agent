# ClearSky Platform Database Schema (Phase 1 MVP)
# Azure Cosmos DB (Serverless) - Cost-Optimized Option

## Cosmos DB Setup

### 1. Create Cosmos DB Account
- API: SQL (Core)
- Capacity Mode: Serverless
- Region: Choose region closest to users
- Consistency: Session (default)

### 2. Create Database
- Database name: `clearsky-platform`
- Throughput: Serverless (auto-scale)

### 3. Create Containers

#### Users Container
- Container name: `users`
- Partition key: `/id`
- Throughput: Serverless (auto-scale)

Document structure:
```json
{
  "id": "uuid",
  "azure_ad_id": "azure_ad_id_or_null",
  "email": "user@example.com",
  "user_type": "end_user|installer|admin",
  "created_at": "2026-10-09T12:00:00Z"
}
```

#### Instances Container
- Container name: `instances`
- Partition key: `/id`
- Throughput: Serverless (auto-scale)

Document structure:
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

#### Instance Access Container
- Container name: `instance_access`
- Partition key: `/id`
- Throughput: Serverless (auto-scale)

Document structure:
```json
{
  "id": "uuid",
  "instance_id": "instance_uuid",
  "user_id": "user_uuid",
  "access_level": "viewer|full_access",
  "created_at": "2026-10-09T12:00:00Z"
}
```

## Cost Comparison

### Cosmos DB Serverless (Current):
- Pay per request (RU)
- ~50K requests/month = ~$0.0125/month
- Auto-scales 0 to max
- Perfect for MVP and early growth

### Azure SQL (Previous):
- Basic Serverless: ~$5-10/month
- Fixed minimum cost
- More expensive for low usage

### Break-even Point:
- Cosmos DB Serverless becomes expensive at ~1.2M RU/day
- Can migrate to Provisioned Throughput at scale (no code changes)

## Migration Path (When Ready to Scale):

When you hit ~$50-100/month in serverless costs:
1. In Azure Portal, change capacity mode from "Serverless" to "Provisioned"
2. Set throughput (e.g., 400 RU/s)
3. No code changes required - same API, same functionality

## Advantages of Cosmos DB Serverless:

✅ Pay only for what you use
✅ Auto-scales from 0 to max
✅ No minimum cost
✅ Seamless migration to provisioned at scale
✅ Global distribution (when needed)
✅ 99.99% SLA available
✅ Built-in indexing
✅ Low latency
✅ Supports all future features (trials, subscriptions, etc.)
