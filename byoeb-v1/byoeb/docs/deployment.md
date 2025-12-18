# BYOEB CI/CD Deployment Guide

## 1) Prerequisites
- Access to the GitHub repo (branch: `a4i/main`)
- **MongoDB Atlas** connection string for *staging* and *production*
- **OpenAI** API keys and endpoints
- **Azure** credentials (Blob, Storage Queue, App Insights, Cognitive Services, Web App)
- **Render.com** account for deployment
- **Microsoft Teams** webhook URL for notifications
- Docker installed (for local testing)

---

## 2) CI/CD Pipeline Overview

Our CI/CD pipeline automatically handles:
- **Testing**: Runs comprehensive tests on every push/PR
- **Building**: Creates Docker images with environment-specific tags
- **Deploying**: Deploys to staging/production based on branch
- **Monitoring**: Sends notifications to Teams for success/failure

### Pipeline Triggers:
- **Push to `a4i/main`**: Deploys to production, runs unit tests
- **Push to `a4i/staging`**: Deploys to staging, runs unit and integration tests
- **Pull to `a4i/main` or `a4i/staging`**: Runs unit tests
- **Manual trigger**: Choose staging or production

## 3) Environment Variables

### GitHub Secrets and Variables (Repository Settings → Secrets and Variables → Actions):
Below are the required repository secrets:
```sh
# Notifications
TEAMS_WEBHOOK_URL             # Microsoft Teams webhook for notifications

# Render.com (Staging)
RENDER_API_KEY                # Render.com API key

# Azure (Production)
AZURE_WEBAPP_PUBLISH_PROFILE  # Web App Publish Profile raw XML string
```

Below are the required repository variables:
```sh
# Render.com (Staging)
RENDER_SERVICE_ID_CHAT_APP    # Render.com service ID for chat_app deployment
RENDER_SERVICE_ID_KB_APP      # Render.com service ID for kb_app deployment

# Azure (Production)
AZURE_WEBAPP_NAME             # Name of the Azure Web App
```

### Render.com Environment Variables:
#### Staging Environment:
```
PORT=10000
APP_ENV=PROD
AZURE_SEARCH_API_KEY=your_staging_key
AZURE_STORAGE_CONNECTION_STRING=your_staging_connection
COSMOS_DB_CONNECTION_STRING=your_staging_mongo
OPENAI_API_ENDPOINT=your_openai_endpoint
OPENAI_API_KEY=your_openai_key
OPENAI_API_KEY_EMBED=your_embed_key
OPENAI_API_TYPE=azure
OPENAI_API_VERSION=2024-02-15-preview
WHATSAPP_TOKEN=your_whatsapp_token
PHONE_NUMBER_ID=your_phone_number_id
VERIFY_TOKEN=your_verify_token
```

#### Production Environment:
```
# Same as staging but with production values
PORT=10000
APP_ENV=PROD
# ... production credentials
```

## 4) Docker Configuration

A Dockerfile is already present in `/byoeb-v1`. The CI/CD pipeline automatically:
- Builds Docker images with environment-specific tags (see below)
- Pushes to GitHub Container Registry (ghcr.io)
- Deploys using the built image

### Docker Image Tags:
- `staging-{sha}`: Latest staging build
- `staging-latest`: Latest staging version
- `production-{sha}`: Production build
- `production-latest`: Latest production version

## 5) Deployment Process

### Automatic Deployment:
1. **Push to `a4i/staging`**:
   - Builds Docker image with `staging-*` tags
   - Runs unit tests
   - Deploys to staging environment
   - Runs integration tests
   - Sends notification to Teams

2. **Push to `a4i/main`**:
   - Builds Docker image with `production-*` tags
   - Runs unit tests
   - Deploys to production environment
   - Sends notification to Teams

### Manual Deployment:
1. Go to **Actions** tab in GitHub
2. Select **CI/CD Pipeline - Build, Test & Deploy**
3. Click **Run workflow**
4. Choose environment (staging/production)
5. Optionally skip tests (use with caution)

## 6) Render.com Setup

### Initial Setup:
1. Log in to Render.com
2. Create a new **Web Service**
3. Connect your GitHub repository
4. Select the `a4i/main` branch
5. Set **Root Directory** to `byoeb-v1/byoeb`
6. Choose **Docker** as the environment
7. Configure environment variables (see section 3)
8. Set **Health Check Path** to `/`
9. Set **Health Check Timeout** to 60 seconds

### Service Configuration:
- **Build Command**: `docker build -t byoeb .`
- **Start Command**: `python -m byoeb.chat_app.run`
- **Health Check**: `GET /`
- **Port**: 10000 (Render's default)

## 7) Monitoring & Notifications

### Teams Notifications:
- **Success**: Sent to "Engineering Huddle" channel when deployment succeeds
- **Failure**: Sent with detailed error information and workflow link
- **Information**: Environment, branch, commit, and deployer details

### Health Monitoring:
- **Health Check**: `GET /` endpoint
- **Status**: Returns "Chat bot is running" with 200 status
- **Monitoring**: Render.com monitors this endpoint

## 8) Testing Endpoints

### Health Check:
```bash
curl https://your-app.onrender.com/
# Expected: "Chat bot is running"
```

### API Documentation:
```bash
curl https://your-app.onrender.com/docs
# Expected: FastAPI Swagger UI
```

### Background Jobs Endpoint:
```bash
curl -X GET https://your-app.onrender.com/jobs \
# Expected: {"jobs": [{...}, {...}, ...], "total": int, "scheduler_running": bool, "timestamp": str}
```

## 9) Troubleshooting

### Common Issues:
1. **500 Error on Startup**:
   - Check environment variables in Render dashboard
   - Verify MongoDB connection string
   - Check health check timeout settings

2. **Deployment Failures**:
   - Check Teams notifications for detailed error info
   - Review GitHub Actions logs
   - Verify Docker image builds successfully

3. **Health Check Failures**:
   - Ensure app binds to correct port (10000)
   - Check if all services initialize properly
   - Verify database connectivity

### Debug Steps:
1. Check Render.com logs for startup errors
2. Verify all environment variables are set
3. Test health endpoint manually
4. Check MongoDB Atlas IP whitelist
5. Review GitHub Actions workflow logs

## 10) Security Notes
- Never commit secrets to the repository
- Use GitHub Secrets for sensitive data
- Staging and production environments are isolated
- All deployments are logged and monitored
- Teams notifications include audit trail

## 11) Support
- For deployment issues: Check Teams notifications
- For code issues: Open GitHub issue
- For urgent problems: Contact maintainer directly
