# AWS Elastic Beanstalk Deployment Guide

## Overview

This document describes the CI/CD pipeline for the **Corrective Self-Reflective RAG** application.
Every push to the `deploy/aws-eb` branch automatically builds a Docker image, pushes it to Amazon ECR,
and deploys it to Elastic Beanstalk — with all environment variables injected from GitHub Secrets.

---

## Infrastructure Summary

| Resource | Value |
|---|---|
| AWS Region | `us-east-1` |
| ECR Repository | `crag-rag-app` |
| ECR Image URL | `685057748560.dkr.ecr.us-east-1.amazonaws.com/crag-rag-app:latest` |
| EB Application | `crag-rag-appp` |
| EB Environment | `crag-rag-prod` |
| EB URL | `crag-rag-prod.eba-nwapefci.us-east-1.elasticbeanstalk.com` |
| S3 Bucket (EB) | `elasticbeanstalk-us-east-1-685057748560` |
| Instance Type | `t3.medium` (single instance) |
| Platform | Docker on 64-bit Amazon Linux 2 v4.5.3 |

---

## Repository Structure (Deployment-Relevant Files)

```
.
├── Dockerfile                        # Multi-stage build (uv + Python 3.12)
├── Dockerrun.aws.json                # Tells EB which ECR image to pull
├── uv.lock                           # Committed lock file for reproducible builds
├── pyproject.toml                    # Python project dependencies
├── .ebextensions/
│   └── storage.config               # EBS volume mount for /var/app/uploads
├── .platform/
│   └── nginx/conf.d/timeout.conf    # Nginx proxy timeout (resolves 504s on PDF upload)
├── .ebignore                         # Files excluded from EB bundle (Dockerfile, etc.)
└── .github/
    └── workflows/
        └── deploy.yml               # GitHub Actions CI/CD workflow
```

---

## CI/CD Workflow

**Trigger:** Push to `deploy/aws-eb` branch.

### Steps

#### 1. Checkout
Checks out the full repository at the pushed commit SHA.

#### 2. Configure AWS Credentials
Authenticates with AWS using `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` from GitHub Secrets.

#### 3. Login to Amazon ECR
Uses the official AWS action to obtain a temporary Docker registry token.

#### 4. Build and Push Docker Image
```bash
docker build --platform linux/amd64 \
  -t 685057748560.dkr.ecr.us-east-1.amazonaws.com/crag-rag-app:<SHA> \
  -t 685057748560.dkr.ecr.us-east-1.amazonaws.com/crag-rag-app:latest .
```
- Tagged with both the full commit SHA and `latest`
- Built for `linux/amd64` to match the EC2 instance architecture

#### 5. Package EB Bundle
```bash
zip -r deploy.zip Dockerrun.aws.json .platform .ebextensions
```
The bundle contains only the EB configuration files. The actual application runs from the ECR image declared in `Dockerrun.aws.json`. The `Dockerfile` is excluded (handled by `.ebignore`).

#### 6. Upload Bundle to S3
Uploads `deploy.zip` to the EB-managed S3 bucket under `crag-rag-appp/<version-label>.zip`.

#### 7. Create EB Application Version
Registers the new S3 bundle as a named application version in EB (e.g. `app-3310941-20260222031422`).

#### 8. Update EB Environment
Deploys the new version **and** sets all environment variables in a single API call:
```bash
aws elasticbeanstalk update-environment \
  --environment-name crag-rag-prod \
  --version-label <version-label> \
  --option-settings file:///tmp/eb-env-settings.json
```
Environment variables are built into a JSON file via Python to safely handle special characters in API keys.

#### 9. Poll for Readiness
Polls every 30 seconds for up to 20 minutes. The AWS built-in waiter is not used because it has a hardcoded ~6.5 minute limit, which is too short for Docker deployments.

---

## GitHub Secrets

All secrets are configured under **Repository Settings → Secrets and variables → Actions**.

| Secret | Description |
|---|---|
| `AWS_ACCESS_KEY_ID` | IAM user access key |
| `AWS_SECRET_ACCESS_KEY` | IAM user secret key |
| `OPENAI_API_KEY` | OpenAI API key for LLM calls |
| `TAVILY_API_KEY` | Tavily API key for web search |
| `QDRANT_URL` | Qdrant Cloud cluster URL |
| `QDRANT_API_KEY` | Qdrant Cloud API key |
| `RERANKER_BACKEND` | Reranker backend (`local`) |
| `UPLOAD_DIR` | Upload directory path (`/var/app/uploads`) |

---

## IAM Permissions Required

The IAM user must have the following minimum permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ecr:GetAuthorizationToken",
        "ecr:BatchCheckLayerAvailability",
        "ecr:GetDownloadUrlForLayer",
        "ecr:BatchGetImage",
        "ecr:InitiateLayerUpload",
        "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload",
        "ecr:PutImage"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject"
      ],
      "Resource": "arn:aws:s3:::elasticbeanstalk-us-east-1-685057748560/*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "elasticbeanstalk:CreateApplicationVersion",
        "elasticbeanstalk:UpdateEnvironment",
        "elasticbeanstalk:DescribeEnvironments",
        "elasticbeanstalk:DescribeApplicationVersions"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": "sts:GetCallerIdentity",
      "Resource": "*"
    }
  ]
}
```

---

## Environment Variables on the EC2 Instance

These are set directly on the EB environment (visible in EB Console → Configuration → Software):

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` | LLM inference |
| `TAVILY_API_KEY` | Web search tool |
| `QDRANT_URL` | Vector store connection |
| `QDRANT_API_KEY` | Vector store authentication |
| `RERANKER_BACKEND` | Controls reranker (`local` = CrossEncoder) |
| `UPLOAD_DIR` | Directory for uploaded PDF files |

---

## Dockerrun.aws.json

EB uses this file to pull the Docker image from ECR. The `latest` tag is always used so EB picks up the newest image on every deploy.

```json
{
  "AWSEBDockerrunVersion": "1",
  "Image": {
    "Name": "685057748560.dkr.ecr.us-east-1.amazonaws.com/crag-rag-app:latest",
    "Update": "true"
  },
  "Ports": [
    { "ContainerPort": 8000 }
  ]
}
```

---

## Health Check

```bash
curl http://crag-rag-prod.eba-nwapefci.us-east-1.elasticbeanstalk.com/health
# Expected: {"status":"healthy"}
```

---

## Deployment Version Naming Convention

Each deploy creates a version label in the format:

```
app-<first-8-chars-of-SHA>-<YYYYMMDDHHmmss>
```

Example: `app-33109418-20260222031422`

This ensures every version is traceable back to its exact commit and timestamp.

---

## Known Issues & Fixes Applied

| Issue | Root Cause | Fix |
|---|---|---|
| 504 Gateway Timeout on PDF upload | Nginx default 60s proxy timeout | Added `.platform/nginx/conf.d/timeout.conf` with 300s timeouts |
| Docker build failure in CI | `uv.lock` was in `.gitignore`, empty file reached `uv sync` | Removed `uv.lock` from `.gitignore`, committed the lock file |
| `No Application named 'crag-rag-app' found` | Workflow had wrong app name (2 p's vs 3 p's) | Corrected to `crag-rag-appp` |
| `Waiter EnvironmentUpdated failed: Max attempts exceeded` | AWS built-in waiter has hardcoded ~6.5 min limit | Replaced with custom 40×30s polling loop (20 min total) |

---

*Author: Sourangshu Pal*
