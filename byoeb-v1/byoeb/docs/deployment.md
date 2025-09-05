## 1) Prerequisites
- Access to the GitHub repo (branch: `a4i/main`)
- **MongoDB Atlas** connection string for *staging*
- Optional: **OpenAI** key/org (can be placeholders)
- Optional: **Azure** credentials (Blob, Storage Queue, App Insights) — can be disabled in staging
- Docker installed (for local testing)

---

## 2) Environment variables

Set these in Render → **Environment** (do **not** commit secrets):
- AZURE_SEARCH_API_KEY
- AZURE_STORAGE_CONNECTION_STRING
- InstrumentationKey
- MONGO_DB_CONNECTION_STRING
- OPENAI_API_ENDPOINT
- OPENAI_API_KEY
- OPENAI_API_KEY_EMBED
- OPENAI_API_TYPE
- OPENAI_API_VERSION
- OPENAI_ORG_ID

---

## 3) Environment & Dockerfile

A Dockerfile is already present in /byoeb-v1/byoeb. You can use this Dockerfile to test the application locally (via docker build and docker run) and the same file can also be used directly for deployment on Render.

## 4) Adding keys.env file
The repository already includes a keys.env file under root this file needs to be present as code reads environment variables from it.

## 5) Deploy to Render or Railway Render
### Render

1. Log in to Render and create a new Web Service.
2. Connect your GitHub repository and select the a4i/main branch.
3. Under Root Directory, set it to byoeb-v1/byoeb (since the Dockerfile is located there).
4. Choose Docker as the environment. Render will automatically detect and build using the provided Dockerfile.
5. Add environment variables in the Render dashboard:
    - Copy values from your keys.env file and .env if needed.
    - Set MONGODB_URI to your staging MongoDB Atlas connection string.
    - Add other required variables (e.g., OPENAI_API_KEY, AZURE_STORAGE_CONNECTION_STRING, etc.).

6. Deploy the service.

### Railway
1. Log in to Railwayand create a new project.
2. Link your GitHub repository and select the a4i/main branch.
3. Add a Service and choose Dockerfile.
    - Make sure the service path is set to byoeb-v1/byoeb.
4. Configure environment variables in Railway’s dashboard:
    - Copy from keys.env and .env as needed.
    - Set MONGODB_URI to the staging MongoDB Atlas connection string.
5. Deploy the service.

## 6. Test Endpoints
After deployment, verify the app is running (e.g., https://your-app.onrender.com or Railway URL).
### Example cURL Requests
#### Health Check
```
curl https://your-app.onrender.com/docs
```

## 7. Troubleshooting
- Check logs in the platform dashboard for errors.
- Ensure all environment variables are set correctly.
- Make sure your MongoDB Atlas IP whitelist allows connections from the platform.

## 8) Notes
- Staging environment is fully isolated from production.
- Do not commit secrets or production credentials.
- For support, open an issue or contact the maintainer.
