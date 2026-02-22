# AWS Elastic Beanstalk Deployment Architecture

Visual reference for the Docker + ECR + Elastic Beanstalk deployment of the Corrective Self-Reflective RAG API.

---

## Deployment Pipeline

How code changes flow from your laptop into a running Beanstalk environment.

```mermaid
flowchart TD
    subgraph Local["💻 Developer Machine"]
        Code([Source Code\napp/ · pyproject.toml · uv.lock])
        Dockerfile([Dockerfile\n.dockerignore])
        DAWSJ([Dockerrun.aws.json\nEB deployment descriptor])
    end

    subgraph Build["🔨 Docker Build  —  docker build --platform linux/amd64"]
        Builder["Builder Stage\nghcr.io/astral-sh/uv:python3.12-bookworm-slim\n① Install system deps\n② uv sync --frozen --no-dev\n③ Pre-download cross-encoder model"]
        Runtime["Runtime Stage\npython:3.12-slim-bookworm\n④ Copy .venv + app + HF cache\n⑤ Create non-root appuser"]
        Image(["Docker Image\ncrag-rag-app:latest\n~3–4 GB compressed"])
    end

    subgraph ECR["📦 Amazon ECR  (Elastic Container Registry)"]
        Repo[("ECR Repository\ncrag-rag-app\nScan-on-push enabled")]
    end

    subgraph EB["🌿 Elastic Beanstalk"]
        EBApp["EB Application\ncrag-rag-app"]
        EBEnv["EB Environment\ncrag-rag-prod\nDocker · Amazon Linux 2023\nt3.large · Single Instance"]
        EnvVars["Environment Variables\nOPENAI_API_KEY\nTAVILY_API_KEY\nQDRANT_URL / QDRANT_API_KEY"]
    end

    subgraph EC2["🖥️ EC2 Instance  (managed by EB)"]
        Docker["Docker Engine"]
        Container(["Container\ncrag-rag-app:latest\nuvicorn --workers 1\nport 8000"])
    end

    Code --> Builder
    Dockerfile --> Builder
    Builder --> Runtime
    Runtime --> Image
    Image -->|docker push| Repo

    DAWSJ -->|zip deploy.zip · eb deploy| EBApp
    EBApp --> EBEnv
    EnvVars --> EBEnv
    Repo -->|IAM pull\naws-elasticbeanstalk-ec2-role| EC2
    EBEnv --> Docker
    Docker --> Container

    style Local fill:#f0f0f0
    style Build fill:#e6f3ff
    style ECR fill:#fff4e6
    style EB fill:#e1f5e1
    style EC2 fill:#ffe6e6
```

---

## Runtime Request Flow

How an HTTP request travels from the internet to the app and back.

```mermaid
flowchart TB
    subgraph Internet["🌐 Internet"]
        Client([HTTP Client\nbrowser · curl · API consumer])
    end

    subgraph AWS["☁️ AWS  —  us-east-1"]
        subgraph EB["Elastic Beanstalk"]
            LB["Load Balancer\nport 80  →  port 8000\n(or direct EC2 in single-instance mode)"]
            HC["EB Health Check\nGET /health  →  200 OK"]
        end

        subgraph EC2["EC2 t3.large"]
            subgraph Container["Docker Container  (crag-rag-app:latest)"]
                Uvicorn["uvicorn\n0.0.0.0:8000\n--workers 1"]

                subgraph FastAPI["FastAPI App"]
                    Upload["/upload/\nDocling parser\nHybridChunker\nDual-vector indexing"]
                    Query["/query/\nRetrieval\nCRAG / Self-Reflective / Both"]
                    Health["/health  /docs"]
                end

                Uvicorn --> Upload
                Uvicorn --> Query
                Uvicorn --> Health
            end
        end
    end

    subgraph External["🔌 External Services"]
        Qdrant[("Qdrant Cloud\nVector Store\ndense + sparse vectors")]
        OpenAI["OpenAI API\nGPT-4o-mini\ntext-embedding-3-small"]
        Tavily["Tavily Search API\nWeb search for CRAG\n(mode=crag/both only)"]
    end

    Client -->|HTTP :80| LB
    LB -->|:8000| Uvicorn
    HC -.->|health poll| Health

    Upload -->|upsert vectors| Qdrant
    Query -->|similarity search| Qdrant
    Query -->|embeddings + LLM| OpenAI
    Query -.->|web search\nif relevance = irrelevant| Tavily

    style Internet fill:#f0f0f0
    style AWS fill:#fff4e6
    style EB fill:#e1f5e1
    style EC2 fill:#e6f3ff
    style Container fill:#e8f4fd
    style External fill:#ffe6e6
```

---

## IAM Permissions Model

How AWS services authenticate with each other.

```mermaid
flowchart LR
    subgraph Developer["👤 Developer"]
        Dev([IAM User / Role\nwith EB + ECR access])
    end

    subgraph Actions["CLI Actions"]
        Push["docker push\necr:GetAuthorizationToken\necr:BatchCheckLayerAvailability\necr:PutImage"]
        Deploy["eb deploy\nelasticbeanstalk:CreateApplicationVersion\nelasticbeanstalk:UpdateEnvironment"]
    end

    subgraph EC2Role["🔑 aws-elasticbeanstalk-ec2-role\n(attached to every EB EC2 instance)"]
        ECRPull["AmazonEC2ContainerRegistryReadOnly\necr:GetDownloadUrlForLayer\necr:BatchGetImage\necr:GetAuthorizationToken"]
        EBManaged["AWSElasticBeanstalkMulticontainerDocker\nAWSElasticBeanstalkWebTier"]
    end

    Dev --> Push
    Dev --> Deploy
    Push -->|authenticates to| ECR[("Amazon ECR")]
    Deploy -->|updates| EBEnv["EB Environment"]
    EBEnv -->|runs on| EC2["EC2 Instance"]
    EC2 -->|assumes| EC2Role
    EC2Role -->|pulls image| ECR

    style Developer fill:#e1f5e1
    style Actions fill:#e6f3ff
    style EC2Role fill:#fff4e6
```

---

## Re-deploy Workflow (Iterative Development)

The cycle for updating the application after code changes.

```mermaid
flowchart LR
    Change([Code Change]) --> Build

    subgraph Build["Local"]
        Build["docker build\n--platform linux/amd64\n-t crag-rag-app:latest ."]
        Push["docker push\n:latest to ECR"]
        Build --> Push
    end

    subgraph Deploy["AWS"]
        EBDeploy["eb deploy\n(Dockerrun.aws.json unchanged)"]
        Pull["EB EC2 pulls\n:latest from ECR\n'Update':'true' forces re-pull"]
        Restart["Container restart\nnew image running"]
        EBDeploy --> Pull --> Restart
    end

    Push --> EBDeploy
    Restart --> Verify

    subgraph Verify["Verify"]
        Health["eb health\ncurl /health → 200"]
        Logs["eb logs --all\ncheck uvicorn output"]
    end

    style Change fill:#e1f5e1
    style Build fill:#e6f3ff
    style Deploy fill:#fff4e6
    style Verify fill:#f0e6ff
```

---

## Container Startup Sequence

What happens inside the container after Beanstalk starts it.

```mermaid
sequenceDiagram
    participant EB as Elastic Beanstalk
    participant Docker as Docker Engine
    participant Container as Container Process
    participant HF as HuggingFace Cache
    participant QD as Qdrant Cloud

    EB->>Docker: docker run crag-rag-app:latest
    Docker->>Container: start uvicorn (--workers 1)
    Container->>Container: load pydantic-settings<br/>read env vars from EB
    Container->>HF: load cross-encoder model<br/>(pre-baked — no network call)
    Container->>QD: connect + verify collection
    Container-->>EB: port 8000 open
    EB->>Container: GET /health
    Container-->>EB: 200 {"status":"healthy"}
    Note over EB: Health = Green ✓
```

---

## Cost Breakdown

```mermaid
pie title Monthly AWS Cost  ~$62/mo  (single-instance, us-east-1)
    "EC2 t3.large  24/7" : 60
    "EBS 20 GB gp3" : 2
    "ECR Storage ~5 GB" : 0.5
```

> Stop the environment when not in use → $0. Qdrant Cloud free tier is $0/mo.

---

## Related Documentation

- **[deployment.md](../deployment.md)** — Step-by-step deployment runbook
- **[workflows/project_architecture.md](./project_architecture.md)** — Application service architecture
- **[workflows/hybrid_search.md](./hybrid_search.md)** — Hybrid search pipeline
- **[Dockerfile](../Dockerfile)** — Container build definition
- **[Dockerrun.aws.json](../Dockerrun.aws.json)** — Beanstalk deployment descriptor
