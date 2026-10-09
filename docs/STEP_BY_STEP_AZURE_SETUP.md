# Step-by-Step Azure Setup Guide

This guide walks you through every click needed to set up Phase 1 of the ClearSky Platform on Azure.

## Prerequisites

- Azure account (free account works)
- GitHub account (for deploying Static Web Apps)
- Basic computer skills

---

## Step 1: Create Resource Group

A Resource Group is a container that holds related Azure resources.

1. Go to https://portal.azure.com
2. Click the **search bar** at the top and type "Resource groups"
3. Click **Resource groups** in the search results
4. Click **+ Create** (or "Create resource group") at the top
5. Fill in the form:
   - **Subscription**: Your subscription (usually selected)
   - **Resource group**: `clearsky-platform-rg` (or any name you prefer)
   - **Region**: Choose a region close to you (e.g., "East US", "West Europe", "UK South")
6. Click **Review + create**
7. Click **Create**
8. Wait for deployment to complete (usually takes 10-30 seconds)
9. Click **Go to resource group** when it appears

---

## Step 2: Create Storage Account

This storage account will be used for both Azure Functions and Blob Storage.

1. In your Resource Group, click **+ Create**
2. Search for "Storage account" and select it
3. Click **Create**
4. Fill in the **Basics** tab:
   - **Subscription**: Your subscription
   - **Resource group**: Select `clearsky-platform-rg` (or the one you created)
   - **Storage account name**: Must be globally unique, e.g., `clearskyplatform1234` (use lowercase letters and numbers only)
   - **Region**: Same region as your Resource Group
   - **Performance**: Standard
   - **Redundancy**: Locally redundant storage (LRS) - cheapest option
5. Click **Next: Advanced**
6. In **Advanced** tab:
   - **Require secure transfer for REST API**: Disabled (for MVP, easier)
7. Click **Next: Networking**
8. **Networking method**: Public endpoint (all networks)
9. Click **Next: Data protection**
10. Leave everything as default
11. Click **Next: Review**
12. Click **Create**
13. Wait for deployment (takes 1-2 minutes)
14. Click **Go to resource** when deployment completes

---

## Step 3: Create Azure Cosmos DB Account

This will be your database for users, instances, and access control.

1. In your Resource Group, click **+ Create**
2. Search for "Azure Cosmos DB" and select it
3. Click **Create**
4. **API option**: Select **"SQL (Core)"** or **"For NoSQL"** (NOT MongoDB)
5. Click **Create** under the SQL option
6. Fill in the **Basics** tab:
   - **Subscription**: Your subscription
   - **Resource group**: Select `clearsky-platform-rg`
   - **Account name**: Must be globally unique, e.g., `clearsky-platform-db1234` (lowercase only)
   - **Location**: Same region as your Resource Group
   - **Capacity mode**: Serverless (important for cost savings)
   - **Apply free tier discount**: Apply if eligible (saves money)
7. Click **Next: Global Distribution**
8. Leave as default (single region for MVP)
9. Click **Next: Networking**
10. **Network access**: All networks (for MVP)
11. Click **Next: Backup policy**
12. Leave as default
13. Click **Next: Encryption**
14. Leave as default
15. Click **Review + create**
16. Click **Create**
17. Wait for deployment (takes 2-5 minutes)
18. Click **Go to resource** when deployment completes

---

## Step 4: Create Cosmos DB Database and Containers

Now we'll create the database structure.

1. In your Cosmos DB account, click **Data Explorer** in the left menu
2. Click **New Container** (or click the "+" next to "Data Explorer")
3. Fill in the form:
   - **Database id**: `clearsky-platform`
   - **Throughput**: Serverless (important for cost savings)
   - **Throughput settings**: Auto-scale
4. Click **OK**
5. Wait for database to be created

### Create Users Container

1. Under the `clearsky-platform` database, click **New Container**
2. Fill in the form:
   - **Container id**: `users`
   - **Partition key**: `/id` (type this exactly, including the slash)
   - **Throughput**: Serverless (should already be selected from database)
3. Click **OK**

### Create Instances Container

1. Click **New Container** again
2. Fill in the form:
   - **Container id**: `instances`
   - **Partition key**: `/id`
   - **Throughput**: Serverless
3. Click **OK**

### Create Instance Access Container

1. Click **New Container** again
2. Fill in the form:
   - **Container id**: `instance_access`
   - **Partition key**: `/id`
   - **Throughput**: Serverless
3. Click **OK**

You should now see three containers under your database.

---

## Step 5: Get Connection Strings

We need to copy the connection strings for the Functions app.

### Cosmos DB Connection String

1. In your Cosmos DB account, click **Settings** in the left menu
2. Click **Keys**
3. Under **Primary connection string**, click the **Copy** button
4. Save this somewhere safe (you'll need it later)

### Blob Storage Connection String

1. Go back to your Storage Account (click on it from the Resource Group)
2. Click **Settings** → **Access keys** in the left menu
3. Click **Show keys** button
4. Under **key1**, copy the **Connection string**
5. Save this somewhere safe

---

## Step 6: Create Azure Functions App

This will host our backend API.

1. In your Resource Group, click **+ Create**
2. Search for "Function App" and select it
3. Click **Create**
4. Fill in the **Basics** tab:
   - **Subscription**: Your subscription
   - **Resource group**: Select `clearsky-platform-rg`
   - **Function App name**: Must be globally unique, e.g., `clearsky-platform-api1234`
   - **Publish**: Code
   - **Runtime stack**: Python
   - **Version**: 3.11
   - **Region**: Same region as your Resource Group
   - **Operating System**: Linux
   - **Hosting Plan and type**: Consumption (Serverless)
   - **Storage account**: Select the storage account you created in Step 2
5. Click **Next: Monitoring**
6. Leave Application Insights disabled for MVP (saves money)
7. Click **Next: Tags**
8. Skip (optional)
9. Click **Next: Review + create**
10. Click **Create**
11. Wait for deployment (takes 2-5 minutes)
12. Click **Go to resource** when deployment completes

---

## Step 7: Configure Azure Functions Environment Variables

Now we'll set up the connection strings.

1. In your Functions App, click **Configuration** in the left menu
2. Click **+ New application setting**
3. Add the following settings one by one:

   **Setting 1:**
   - **Name**: `COSMOS_DB_CONNECTION_STRING`
   - **Value**: Paste the Cosmos DB connection string you copied in Step 5
   - Click **OK**

   **Setting 2:**
   - **Name**: `AZURE_BLOB_CONNECTION_STRING`
   - **Value**: Paste the Blob Storage connection string you copied in Step 5
   - Click **OK**

   **Setting 3:**
   - **Name**: `JWT_SECRET`
   - **Value**: Generate a random string (e.g., use a password generator)
   - Click **OK**

4. Click **Save** at the top
5. Click **Continue** if prompted

---

## Step 8: Deploy Azure Functions Code

Now we'll deploy the Python code to Azure Functions.

### Option A: Using Visual Studio Code (Recommended)

1. Install VS Code if you don't have it
2. Install the "Azure Functions" extension
3. Open your `clearsky_agent` folder in VS Code
4. Right-click on the `azure_functions` folder
5. Select **Deploy to Function App**
6. Select your Function App (the one you created)
7. Wait for deployment to complete

### Option B: Using Azure CLI

1. Install Azure CLI: https://docs.microsoft.com/cli/azure/install-azure-cli
2. Open terminal/command prompt
3. Run:
   ```bash
   cd /path/to/clearsky_agent/azure_functions
   func azure functionapp publish clearsky-platform-api1234 --python
   ```
   (replace with your actual Function App name)

### Option C: Using ZIP Deploy (Simplest)

1. In your Functions App in Azure Portal, click **Deployment Center** in the left menu
2. Click **Settings**
3. Under **Deployment source**, select **Local Git**
4. Click **Save**
5. Follow the instructions to push your code via Git

---

## Step 9: Test Azure Functions

Let's verify the Functions are working.

1. In your Functions App, click **Functions** in the left menu
2. You should see your function endpoints listed
3. Click on one of the functions (e.g., `register_user`)
4. Click **Get Function URL** at the top
5. Click **Default (Function key)**
6. Copy the URL
7. Test it using a tool like Postman or curl:
   ```bash
   curl -X POST "YOUR_FUNCTION_URL" -H "Content-Type: application/json" -d '{"email":"test@example.com","user_type":"end_user"}'
   ```

---

## Step 10: Create Azure Static Web App

This will host your web dashboard.

1. In your Resource Group, click **+ Create**
2. Search for "Static Web App" and select it
3. Click **Create**
4. Fill in the **Basics** tab:
   - **Subscription**: Your subscription
   - **Resource group**: Select `clearsky-platform-rg`
   - **Static Web App name**: Must be globally unique, e.g., `clearsky-platform-web1234`
   - **Region**: Same region as your Resource Group
5. Click **Next: Deployment**
6. **Source**: GitHub
7. **Organization**: Select your GitHub organization or username
8. **Repository**: Select `clearsky_agent`
9. **Branch**: `main`
10. **Build preset**: Custom
11. **App location**: `/web_app`
12. **Api location**: Leave blank (we're not deploying an API here)
13. **Artifacts location**: Leave blank
14. Click **Review + create**
15. Click **Create**
16. Wait for deployment (takes 2-5 minutes)
17. Click **Go to resource** when deployment completes

---

## Step 11: Test the Web App

1. In your Static Web App, click the URL (e.g., `https://clearsky-platform-web1234.azurestaticapps.net`)
2. The web app should load in your browser
3. Click the ⚙️ **Settings** button
4. Select **Platform API** mode
5. Enter your Functions App URL: `https://clearsky-platform-api1234.azurewebsites.net`
6. Click **Save**
7. Try loading data (you'll need a registered instance first)

---

## Step 12: Deploy HAOS Add-on

Now let's deploy the updated add-on to your Home Assistant.

1. Push your changes to GitHub:
   ```bash
   git push origin main
   ```

2. In Home Assistant:
   - Go to **Settings** → **Add-ons** → **Add-on Store**
   - Refresh the page
   - You should see an "Update" badge on ClearSky Snapshot Agent
   - Click **Update**
   - Wait for installation to complete

3. Configure the add-on:
   - Go to **Settings** → **Add-ons** → **ClearSky Snapshot Agent**
   - Open **Configuration** tab
   - Set `platform_enabled: true`
   - Set `platform_api_url: "https://your-functions-app.azurewebsites.net"`
   - Set `registration_token: ""` (leave empty for now)
   - Set `instance_name: "My Home"`
   - Click **Save**
   - Restart the add-on

---

## Step 13: Test End-to-End Flow

1. Register a user via the API (you can use Postman or curl):
   ```bash
   curl -X POST "https://your-functions-app.azurewebsites.net/api/users/register" \
     -H "Content-Type: application/json" \
     -d '{"email":"test@example.com","user_type":"end_user"}'
   ```

2. Copy the `registration_token` from the response

3. Update your HAOS add-on configuration with the registration token

4. Restart the add-on

5. The add-on should automatically register the instance

6. In the web app, refresh and you should see the instance listed

---

## Troubleshooting

### Functions not deploying:
- Check the Deployment Center logs in Azure Portal
- Ensure your Python version matches (3.11)
- Check the requirements.txt has all dependencies

### Cosmos DB connection errors:
- Verify the connection string is correct
- Check that the database and containers exist
- Ensure Serverless mode is enabled

### Web app not loading:
- Check the deployment logs in Static Web App
- Verify the build succeeded
- Check the browser console for errors

### Add-on not registering:
- Check the add-on logs in Home Assistant
- Verify the platform_api_url is correct
- Ensure the Functions app is running

---

## Cost Verification

After setup, verify your costs:

1. Go to your Resource Group
2. Click **Cost Management** in the left menu
3. View the cost breakdown
4. You should see ~$2-5/month (or $0 if using free tiers)

---

## Next Steps

Once everything is working:
1. Implement Azure AD authentication (deferred from Phase 1)
2. Add error handling and logging
3. Set up monitoring with Application Insights
4. Test with multiple instances
5. Plan Phase 2 features (trials, subscriptions)
