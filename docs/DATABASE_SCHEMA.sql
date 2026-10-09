-- ClearSky Platform Database Schema (Phase 1 MVP)
-- Run this in Azure SQL Database Query Editor

-- Users Table
CREATE TABLE users (
  id UNIQUEIDENTIFIER PRIMARY KEY DEFAULT NEWID(),
  azure_ad_id NVARCHAR(255) UNIQUE,
  email NVARCHAR(255),
  user_type NVARCHAR(50) CHECK (user_type IN ('end_user', 'installer', 'admin')),
  created_at DATETIME2 DEFAULT GETDATE()
);

-- Instances Table
CREATE TABLE instances (
  id UNIQUEIDENTIFIER PRIMARY KEY DEFAULT NEWID(),
  instance_uuid NVARCHAR(255) UNIQUE,
  owner_id UNIQUEIDENTIFIER NOT NULL,
  instance_name NVARCHAR(255),
  storage_container NVARCHAR(255),
  ha_version NVARCHAR(50),
  last_sync DATETIME2,
  created_at DATETIME2 DEFAULT GETDATE(),
  FOREIGN KEY (owner_id) REFERENCES users(id)
);

-- Instance Access Table
CREATE TABLE instance_access (
  id UNIQUEIDENTIFIER PRIMARY KEY DEFAULT NEWID(),
  instance_id UNIQUEIDENTIFIER NOT NULL,
  user_id UNIQUEIDENTIFIER NOT NULL,
  access_level NVARCHAR(50) CHECK (access_level IN ('viewer', 'full_access')),
  created_at DATETIME2 DEFAULT GETDATE(),
  FOREIGN KEY (instance_id) REFERENCES instances(id),
  FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Indexes for performance
CREATE INDEX idx_instances_owner ON instances(owner_id);
CREATE INDEX idx_instance_access_instance ON instance_access(instance_id);
CREATE INDEX idx_instance_access_user ON instance_access(user_id);
CREATE INDEX idx_instances_uuid ON instances(instance_uuid);
