# AWS Elastic Beanstalk Deployment Guide

Deploy the Corrective Self-Reflective RAG API on AWS Elastic Beanstalk using a pre-built Docker image hosted in Amazon ECR.

## Architecture Overview

```
Internet
   │  HTTP :80
   ▼
Elastic Beanstalk Load Balancer  ←── EB Health Checks
   │
   ▼
EC2 t3.large  (2 vCPU · 8 GB RAM · Amazon Linux 2023)
   │
   ▼  Docker pull on deploy
Docker container  (crag-rag-app:latest · port 8000)
   │
   ├──► Qdrant Cloud   (vector store)
   ├──► OpenAI API     (LLM + embeddings)
   └──► Tavily API     (web search for CRAG)

ECR  ──►  EC2 instance pulls image via IAM role
EB env vars  ──►  API keys injected at container start
```

See `workflows/aws_eb_deployment.md` for full Mermaid diagrams.

---

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| AWS CLI | 2.x | `brew install awscli` |
| EB CLI | latest | `pip install awsebcli` |
| Docker | 20.x+ | [docker.com](https://docs.docker.com/get-docker/) |
| AWS account | — | IAM user with AdministratorAccess or scoped permissions |

```bash
# Verify all tools are present
aws --version
eb --version
docker --version
aws sts get-caller-identity   # confirms auth
```

---

## Phase 1 — Build & Push Image to ECR

```bash
AWS_REGION="us-east-1"
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_REPO="crag-rag-app"
ECR_IMAGE="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPO:latest"

# Create the ECR repository (one-time)
aws ecr create-repository \
    --repository-name $ECR_REPO \
    --region $AWS_REGION \
    --image-scanning-configuration scanOnPush=true

# Authenticate Docker to ECR
aws ecr get-login-password --region $AWS_REGION | \
    docker login --username AWS --password-stdin \
    $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com

# Build for linux/amd64 (required on Apple Silicon M1/M2/M3)
docker build --platform linux/amd64 -t $ECR_REPO:latest .

# Tag and push
docker tag $ECR_REPO:latest $ECR_IMAGE
docker push $ECR_IMAGE
```

> **Build time note:** The first build downloads system packages and the
> `cross-encoder/ms-marco-MiniLM-L-6-v2` model (~80 MB). Subsequent builds
> use Docker's layer cache and are much faster.

---

## Phase 2 — Grant EC2 Instance ECR Pull Access

Elastic Beanstalk's EC2 instances use the IAM role
`aws-elasticbeanstalk-ec2-role` to authenticate with AWS services.
Attach the managed ECR read policy so the instance can pull your image:

```bash
aws iam attach-role-policy \
    --role-name aws-elasticbeanstalk-ec2-role \
    --policy-arn arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly
```

> If `aws-elasticbeanstalk-ec2-role` does not exist yet, Beanstalk creates it
> automatically on the first `eb create`. You can attach the policy from the
> **IAM Console → Roles** after the environment is created.

---

## Phase 3 — Update Dockerrun.aws.json

Fill in your real AWS account ID and region in `Dockerrun.aws.json`:

```bash
# Check the placeholder values
cat Dockerrun.aws.json
```

Edit the `"Name"` field to match your ECR image URI:

```json
"Name": "123456789012.dkr.ecr.us-east-1.amazonaws.com/crag-rag-app:latest"
```

Verify it matches what you pushed:

```bash
aws ecr describe-images \
    --repository-name $ECR_REPO \
    --region $AWS_REGION \
    --query 'imageDetails[*].imageTags'
```

---

## Phase 4 — Initialize Beanstalk Application

Run this once from the project root:

```bash
eb init crag-rag-app \
    --platform "Docker running on 64bit Amazon Linux 2023" \
    --region $AWS_REGION
# Prompts:
#   Use CodeCommit? → No
#   Set up SSH?     → Yes (optional, useful for debugging)
```

This creates `.elasticbeanstalk/config.yml` (already gitignored).

---

## Phase 5 — Create the Beanstalk Environment

```bash
# Single-instance mode (no load balancer — simplest, ~$62/mo)
eb create crag-rag-prod \
    --instance-type t3.large \
    --single

# OR with load balancer + auto-scaling (production-grade, ~$78/mo+)
eb create crag-rag-prod \
    --instance-type t3.large
```

> **Instance size rationale:** `t3.large` (8 GB RAM) is the recommended
> minimum. The container loads sentence-transformers (cross-encoder ~500 MB),
> faiss, and docling at startup — peak RSS is typically 4–6 GB.

---

## Phase 6 — Set Environment Variables (API Keys)

API keys are stored encrypted inside Beanstalk and injected as container
environment variables at runtime. No `.env` file is needed in the image.

```bash
eb setenv \
    OPENAI_API_KEY="sk-your-openai-key" \
    TAVILY_API_KEY="tvly-your-tavily-key" \
    QDRANT_URL="https://your-cluster.eu-central-1-0.aws.cloud.qdrant.io" \
    QDRANT_API_KEY="your-qdrant-api-key" \
    RERANKER_BACKEND="local" \
    UPLOAD_DIR="/var/app/uploads"
```

### All supported environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENAI_API_KEY` | Yes | — | OpenAI API key |
| `TAVILY_API_KEY` | Yes | — | Tavily search API key (CRAG mode) |
| `QDRANT_URL` | Yes | `http://localhost:6333` | Qdrant Cloud cluster URL |
| `QDRANT_API_KEY` | Yes (cloud) | `None` | Qdrant Cloud API key |
| `QDRANT_COLLECTION_NAME` | No | `crag_documents` | Qdrant collection name |
| `EMBEDDING_MODEL` | No | `text-embedding-3-small` | OpenAI embedding model |
| `LLM_MODEL` | No | `gpt-4o-mini` | OpenAI chat model |
| `RERANKER_BACKEND` | No | `local` | `local` or `voyage` |
| `VOYAGE_API_KEY` | No | `None` | Required if `RERANKER_BACKEND=voyage` |
| `UPLOAD_DIR` | No | `uploads` | Container path for uploaded files |
| `HYBRID_SEARCH_ENABLED` | No | `true` | Enable/disable hybrid search |
| `SPARSE_VECTOR_ENABLED` | No | `true` | Enable/disable sparse vectors |
| `RRF_K` | No | `60` | RRF fusion parameter |
| `HYDE_ENABLED_BY_DEFAULT` | No | `false` | Enable HYDE query expansion by default |
| `RERANKING_ENABLED_BY_DEFAULT` | No | `false` | Enable reranking by default |

---

## Phase 7 — Deploy

```bash
# Bundle only the Beanstalk descriptor
zip deploy.zip Dockerrun.aws.json

# Deploy (EB pulls the ECR image on the EC2 instance)
eb deploy

# Stream deployment logs
eb logs
```

> The `"Update": "true"` flag in `Dockerrun.aws.json` forces Beanstalk to
> re-pull the `:latest` tag on every `eb deploy`, so you don't need to change
> the image tag between deploys.

**Alternative — Beanstalk Console upload:**
1. Elastic Beanstalk → Create Environment → Web server → Docker platform
2. Upload `deploy.zip` as the application version
3. Set environment variables in **Configuration → Software**

---

## Verify the Deployment

```bash
# Open app in default browser
eb open

# Check environment health (should show "Green")
eb health

# Get the public URL
eb status | grep CNAME

# Test health endpoint
curl http://<your-env>.elasticbeanstalk.com/health
# Expected: {"status":"healthy"}

# Test upload
curl -X POST http://<your-env>.elasticbeanstalk.com/upload/ \
  -F "file=@document.pdf"

# Test query
curl -X POST http://<your-env>.elasticbeanstalk.com/query/ \
  -H "Content-Type: application/json" \
  -d '{"query": "What is the main topic?", "mode": "both"}'

# View Swagger UI
open http://<your-env>.elasticbeanstalk.com/docs
```

### End-to-end verification checklist

- [ ] `docker build` succeeds locally
- [ ] `docker run -p 8000:8000 --env-file .env crag-rag-app:latest` works locally
- [ ] `curl localhost:8000/health` → `{"status":"healthy"}`
- [ ] Image visible in ECR console
- [ ] `eb status` shows `Health: Green`
- [ ] `curl http://<eb-url>/health` → 200
- [ ] PDF upload and query work end-to-end

---

## Re-deploy After Code Changes

```bash
# 1. Rebuild and push updated image to ECR
docker build --platform linux/amd64 -t $ECR_REPO:latest .
docker push $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPO:latest

# 2. Re-deploy (Beanstalk re-pulls :latest from ECR)
eb deploy
```

---

## Cost Estimate

All prices are for `us-east-1`, on-demand, single-instance mode.

| Resource | Configuration | Monthly Cost |
|---|---|---|
| EC2 t3.large | 2 vCPU · 8 GB · 24/7 | ~$60/mo |
| EBS gp3 | 20 GB root volume | ~$2/mo |
| ECR storage | ~5 GB image | ~$0.50/mo |
| Qdrant Cloud | Free tier (1 GB) | $0.00/mo |
| **Total** | | **~$62/mo** |

> Stop or terminate the environment when not in use to avoid EC2 charges.

---

## Stop / Teardown

```bash
# Suspend — terminate the EC2 instance (stops billing; environment config preserved)
eb terminate crag-rag-prod

# Nuke everything — delete the EB application entirely
eb terminate --all

# Delete the ECR repository
aws ecr delete-repository \
    --repository-name $ECR_REPO \
    --region $AWS_REGION \
    --force
```

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---|---|---|
| `Health: Red` after deploy | Container failed to start | `eb logs --all` — look for Python/uvicorn errors |
| `docker pull` fails on EC2 | Missing ECR IAM policy | Attach `AmazonEC2ContainerRegistryReadOnly` to `aws-elasticbeanstalk-ec2-role` |
| `403 Forbidden` on ECR push | Docker not authenticated | Re-run `aws ecr get-login-password …` |
| Container OOM killed | Not enough RAM | Upgrade to `t3.xlarge` (16 GB) |
| Slow cold start (~60s) | Models loading into memory | Expected — cross-encoder is pre-baked but still loaded at process start |
| `pydantic ValidationError` at startup | Missing required env var | Check `eb setenv` — `OPENAI_API_KEY` and `TAVILY_API_KEY` are required |
| Uploaded files disappear | Ephemeral EC2 storage | Expected — file uploads are transient; vectors persist in Qdrant Cloud |

---

## Key Design Notes

1. **`--workers 1`** — `sentence-transformers` and `faiss` are not fork-safe.
   Scale by adding more Beanstalk instances, not by increasing workers.
2. **File uploads are ephemeral** — `uploads/` lives on the EC2 instance and
   is lost on restart or re-deploy. This is intentional: document vectors are
   persisted in Qdrant Cloud.
3. **Cross-encoder model is pre-baked** — `cross-encoder/ms-marco-MiniLM-L-6-v2`
   is downloaded during `docker build`, so there is no HuggingFace network call
   at container startup.
4. **`pydantic-settings` reads EB env vars directly** — zero code changes are
   needed to switch from `.env` file to Beanstalk environment variables.
5. **`:latest` + `"Update": "true"`** — Beanstalk re-pulls the image on every
   `eb deploy`. No tag management needed for iterative development.

---

## Related Files

| File | Purpose |
|---|---|
| `Dockerfile` | Builds the container image |
| `.dockerignore` | Excludes `.venv`, secrets, tests from the build context |
| `Dockerrun.aws.json` | Tells Beanstalk which ECR image to pull and run |
| `app/config.py` | `pydantic-settings` — reads all config from environment variables |
| `pyproject.toml` + `uv.lock` | Required in build context for `uv sync --frozen` |
| `workflows/aws_eb_deployment.md` | Mermaid architecture and deployment flow diagrams |
