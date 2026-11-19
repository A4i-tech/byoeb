# BYOEB CI/CD Deployment Guide

## 1) Prerequisites
- Access to the GitHub repo (branch: `a4i/main`)
- **MongoDB Atlas** connection string for *staging* and *production*
- **OpenAI** API keys and endpoints
- **Azure** credentials (Blob, Storage Queue, App Insights, Cognitive Services, Web App)
- Access to the kube-dev cluster (staging) and the Azure Web App (production)
- **Microsoft Teams** webhook URL for notifications
- Docker installed (for local testing)

---

## 2) CI/CD Pipeline Overview

Our CI/CD pipeline automatically handles:
- **Testing**: Runs comprehensive tests on every push/PR
- **Building**: Creates Docker images with environment-specific tags
- **Deploying**: Pushes the image; staging is rolled out on kube-dev by ArgoCD Image Updater, production is deployed to the Azure Web App
- **Monitoring**: Sends notifications to Teams for success/failure

### Pipeline Triggers:
- **Push to `a4i/main`**: Deploys to production, runs unit tests
- **Push to `a4i/staging`**: Publishes the staging image, runs unit and integration tests against kube-dev
- **Pull to `a4i/main` or `a4i/staging`**: Runs unit tests
- **Manual trigger**: Choose staging or production

## 3) Environment Variables

### GitHub Secrets and Variables (Repository Settings → Secrets and Variables → Actions):
Below are the required repository secrets:
```sh
# Notifications
TEAMS_WEBHOOK_URL             # Microsoft Teams webhook for notifications

STAGING_ENVS                  # Raw contents of keys.env

# Azure (Production)
AZURE_WEBAPP_PUBLISH_PROFILE  # Web App Publish Profile raw XML string
```

Below are the required repository variables:
```sh
# Azure (Production)
AZURE_WEBAPP_NAME             # Name of the Azure Web App
```

### Runtime Environment Variables:
Staging runtime configuration lives in the `byoeb-chat-app-secret` ExternalSecret in `A4i-tech/infra-ops` (`partners/byoeb`), backed by Key Vault. Production uses the Azure Web App settings.

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
   - ArgoCD Image Updater rolls the new image out on kube-dev
   - Runs integration tests against `https://byoeb-dev.a4i-lab.in`
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

## 6) Staging on kube-dev

Staging runs in the `byoeb` namespace on kube-dev, managed by ArgoCD from `partners/byoeb` in `A4i-tech/infra-ops`.

- **Image**: `ghcr.io/a4i-tech/byoeb:staging-latest`
- **URL**: `https://byoeb-dev.a4i-lab.in`
- **Health Check**: `GET /`
- **Port**: 8000

## 7) Monitoring & Notifications

### Teams Notifications:
- **Success**: Sent to "Engineering Huddle" channel when deployment succeeds
- **Failure**: Sent with detailed error information and workflow link
- **Information**: Environment, branch, commit, and deployer details

### Health Monitoring:
- **Health Check**: `GET /` endpoint
- **Status**: Returns "Chat bot is running" with 200 status
- **Monitoring**: kube-dev liveness and readiness probes use this endpoint

## 8) Testing Endpoints

### Health Check:
```bash
curl https://byoeb-dev.a4i-lab.in/
# Expected: "Chat bot is running"
```

### API Documentation:
```bash
curl https://byoeb-dev.a4i-lab.in/docs
# Expected: FastAPI Swagger UI
```

### Background Jobs Endpoint:
```bash
curl -X GET https://byoeb-dev.a4i-lab.in/jobs \
# Expected: {"jobs": [{...}, {...}, ...], "total": int, "scheduler_running": bool, "timestamp": str}
```

## 9) Troubleshooting

### Common Issues:
1. **500 Error on Startup**:
   - Check the `byoeb-chat-app-secret` ExternalSecret and pod logs on kube-dev
   - Verify MongoDB connection string
   - Check the pod readiness probe

2. **Deployment Failures**:
   - Check Teams notifications for detailed error info
   - Review GitHub Actions logs
   - Verify Docker image builds successfully

3. **Health Check Failures**:
   - Ensure app binds to port 8000
   - Check if all services initialize properly
   - Verify database connectivity

### Debug Steps:
1. Check the `byoeb-chat-app` pod logs on kube-dev for startup errors
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
