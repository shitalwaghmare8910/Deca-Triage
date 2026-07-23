# Docker Deployment Guide — DECA — Decade of Autonomous Triage

This guide explains how the Dockerfiles are structured and provides the exact
**build & push** commands for every service: the 8 agents, the STIP Generator,
and the Backend + Frontend UI.

All images are built with **BuildKit (`buildctl`)** and pushed to the internal
**Artifactory** registry, matching the existing project workflow.

---

## 1. Service / Port / Image reference

| # | Service | Source path | Port | Run command (in image) | Build context |
|---|---------|-------------|------|------------------------|---------------|
| 1 | Root Orchestrator | `src/agents/root-orchestrator` | 8080 | `uvicorn agent:app` | service dir |
| 2 | Knowledge Ingestion | `src/agents/knowledge_ingestion` | 8001 | `uvicorn agent:app` | **repo root** |
| 3 | Postgres Agent | `src/agents/postgres-agent` | 8003 | `uvicorn agent:app` | service dir |
| 4 | Critic Agent | `src/agents/critic-agent` | 8004 | `uvicorn agent:app` | service dir |
| 5 | Concept Agent | `src/agents/concept-agent` | 8005 | `uvicorn agent:app` | service dir |
| 6 | Jira Agent | `src/agents/jira-agent` | 8006 | `uvicorn agent:app` | service dir |
| 7 | Incident Logger Agent | `src/agents/incident-logger-agent` | 8007 | `uvicorn agent:app` | service dir |
| 8 | Notification Agent | `src/agents/notification-agent` | 8008 | `uvicorn agent:app` | service dir |
| 9 | STIP Generator | `src/stip_generater` | 5001 | `python server.py` (Flask) | service dir |
| 10 | Backend + Frontend UI | `src/backend` | 5000 | `python server.py` (Flask) | service dir |

> **Knowledge Ingestion is the only exception**: it imports the shared package
> `src.common.db_connection`, so its image must be built from the **repository
> root** (so `src/common` can be copied in). Every other service builds from its
> own directory.

---

## 2. Prerequisites

- Access to the BuildKit daemon:
  `tcp://buildkitd.buildkit.svc.cluster.local:1234`
- Network/credentials for the Artifactory registry
  `artifactory.sdlc.ctl.gcp.db.com`.
- A per-service `requirements.txt` (already present in each service directory).
- `buildctl` available on your PATH.

Set the registry base once per shell session:

```bash
export REGISTRY="artifactory.sdlc.ctl.gcp.db.com/dkr-all/com/db/aiplatform/apps"
export BUILDKIT_ADDR="tcp://buildkitd.buildkit.svc.cluster.local:1234"
export TAG="0.1.0"
```

---

## 3. How a Dockerfile is structured

Every service uses the same base image and pattern. Anatomy of an **agent**
Dockerfile (FastAPI / uvicorn):

```dockerfile
FROM artifactory.sdlc.ctl.gcp.db.com/dkr-public-local/gcp-community-images/python:3.10

# 1. Workdir inside the container
WORKDIR /app

# 2. Runtime env (no .pyc files, unbuffered logs)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/root/.local/bin:/usr/local/bin:$PATH"

# 3. Install deps first (better layer caching)
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir \
       --index-url https://<user>:<token>@artifactory.sdlc.ctl.gcp.db.com/artifactory/api/pypi/pypi/simple \
       -r requirements.txt

# 4. Copy app code
COPY . .

# 5. Expose the service port
EXPOSE 8080

# 6. Start the FastAPI app (module agent.py -> app object)
ENTRYPOINT []
CMD ["python", "-m", "uvicorn", "agent:app", "--host", "0.0.0.0", "--port", "8080"]
```

Key rules:
- **Agents** run `agent:app` (the FastAPI `app` lives in `agent.py`) — not
  `main:app`.
- **Flask services** (STIP Generator, UI) run `python server.py`; the port is
  baked into `server.py` (`app.run(..., port=...)`).
- Change only the `EXPOSE` line and the `--port` in `CMD` per service.

A **Flask** service Dockerfile differs only in the last steps:

```dockerfile
EXPOSE 5001
ENTRYPOINT []
CMD ["python", "server.py"]
```

---

## 4. The build & push command (BuildKit)

Generic form — pushes directly to the registry (`push=true`):

```bash
buildctl --addr "$BUILDKIT_ADDR" build \
  --frontend dockerfile.v0 \
  --local context=<CONTEXT_DIR> \
  --local dockerfile=<DOCKERFILE_DIR> \
  --output type=image,name=<IMAGE_URI>,push=true
```

- `context`    — files available to `COPY` (the build root).
- `dockerfile` — directory that contains the `Dockerfile`.
- `name`       — full image URI including tag.

---

## 5. Per-service build & push commands

> Run all commands from the **repository root**
> (`/home/jovyan/work/gps-ai-telda-poc-final-copy`) unless noted.

### 5.1 Root Orchestrator (8080)

```bash
export IMAGE_URI="$REGISTRY/root-orchestrator:$TAG"
buildctl --addr "$BUILDKIT_ADDR" build \
  --frontend dockerfile.v0 \
  --local context=src/agents/root-orchestrator \
  --local dockerfile=src/agents/root-orchestrator \
  --output type=image,name=$IMAGE_URI,push=true
```

### 5.2 Knowledge Ingestion (8001) — builds from REPO ROOT

```bash
export IMAGE_URI="$REGISTRY/knowledge-ingestion:$TAG"
buildctl --addr "$BUILDKIT_ADDR" build \
  --frontend dockerfile.v0 \
  --local context=. \
  --local dockerfile=src/agents/knowledge_ingestion \
  --output type=image,name=$IMAGE_URI,push=true
```

### 5.3 Postgres Agent (8003)

```bash
export IMAGE_URI="$REGISTRY/postgres-agent:$TAG"
buildctl --addr "$BUILDKIT_ADDR" build \
  --frontend dockerfile.v0 \
  --local context=src/agents/postgres-agent \
  --local dockerfile=src/agents/postgres-agent \
  --output type=image,name=$IMAGE_URI,push=true
```

### 5.4 Critic Agent (8004)

```bash
export IMAGE_URI="$REGISTRY/critic-agent:$TAG"
buildctl --addr "$BUILDKIT_ADDR" build \
  --frontend dockerfile.v0 \
  --local context=src/agents/critic-agent \
  --local dockerfile=src/agents/critic-agent \
  --output type=image,name=$IMAGE_URI,push=true
```

### 5.5 Concept Agent (8005)

```bash
export IMAGE_URI="$REGISTRY/concept-agent:$TAG"
buildctl --addr "$BUILDKIT_ADDR" build \
  --frontend dockerfile.v0 \
  --local context=src/agents/concept-agent \
  --local dockerfile=src/agents/concept-agent \
  --output type=image,name=$IMAGE_URI,push=true
```

### 5.6 Jira Agent (8006)

```bash
export IMAGE_URI="$REGISTRY/jira-agent:$TAG"
buildctl --addr "$BUILDKIT_ADDR" build \
  --frontend dockerfile.v0 \
  --local context=src/agents/jira-agent \
  --local dockerfile=src/agents/jira-agent \
  --output type=image,name=$IMAGE_URI,push=true
```

### 5.7 Incident Logger Agent (8007)

```bash
export IMAGE_URI="$REGISTRY/incident-logger-agent:$TAG"
buildctl --addr "$BUILDKIT_ADDR" build \
  --frontend dockerfile.v0 \
  --local context=src/agents/incident-logger-agent \
  --local dockerfile=src/agents/incident-logger-agent \
  --output type=image,name=$IMAGE_URI,push=true
```

### 5.8 Notification Agent (8008)

```bash
export IMAGE_URI="$REGISTRY/notification-agent:$TAG"
buildctl --addr "$BUILDKIT_ADDR" build \
  --frontend dockerfile.v0 \
  --local context=src/agents/notification-agent \
  --local dockerfile=src/agents/notification-agent \
  --output type=image,name=$IMAGE_URI,push=true
```

### 5.9 STIP Generator (5001)

```bash
export IMAGE_URI="$REGISTRY/stip-generator:$TAG"
buildctl --addr "$BUILDKIT_ADDR" build \
  --frontend dockerfile.v0 \
  --local context=src/stip_generater \
  --local dockerfile=src/stip_generater \
  --output type=image,name=$IMAGE_URI,push=true
```

### 5.10 Backend + Frontend UI (5000)

```bash
export IMAGE_URI="$REGISTRY/triage-ui:$TAG"
buildctl --addr "$BUILDKIT_ADDR" build \
  --frontend dockerfile.v0 \
  --local context=src/backend \
  --local dockerfile=src/backend \
  --output type=image,name=$IMAGE_URI,push=true
```

---

## 6. Build everything in one go (optional)

From the repository root:

```bash
export REGISTRY="artifactory.sdlc.ctl.gcp.db.com/dkr-all/com/db/aiplatform/apps"
export BUILDKIT_ADDR="tcp://buildkitd.buildkit.svc.cluster.local:1234"
export TAG="0.1.0"

build() { # build <image-name> <context> <dockerfile-dir>
  local uri="$REGISTRY/$1:$TAG"
  echo ">>> Building $uri"
  buildctl --addr "$BUILDKIT_ADDR" build \
    --frontend dockerfile.v0 \
    --local context="$2" \
    --local dockerfile="$3" \
    --output type=image,name="$uri",push=true
}

build root-orchestrator      src/agents/root-orchestrator       src/agents/root-orchestrator
build knowledge-ingestion    .                                  src/agents/knowledge_ingestion   # repo-root context
build postgres-agent         src/agents/postgres-agent          src/agents/postgres-agent
build critic-agent           src/agents/critic-agent            src/agents/critic-agent
build concept-agent          src/agents/concept-agent           src/agents/concept-agent
build jira-agent             src/agents/jira-agent              src/agents/jira-agent
build incident-logger-agent  src/agents/incident-logger-agent   src/agents/incident-logger-agent
build notification-agent     src/agents/notification-agent      src/agents/notification-agent
build stip-generator         src/stip_generater                 src/stip_generater
build triage-ui              src/backend                        src/backend
```

---

## 7. Runtime configuration (env vars)

The images do **not** bake secrets. Provide these at deploy time (Cloud Run /
Kubernetes env or mounted secrets):

| Variable | Used by | Purpose |
|----------|---------|---------|
| `GOOGLE_CLOUD_PROJECT` | agents using Vertex AI | GCP project id |
| `GOOGLE_CLOUD_LOCATION` | agents using Vertex AI | Region (e.g. `us-central1`) |
| `KNOWLEDGE_BUCKET_NAME` | Knowledge Ingestion | GCS bucket for PDFs |
| `INSTANCE_CONNECTION_NAME` | Postgres / Knowledge | Cloud SQL instance |
| `DB_USER`, `DB_PASS`, `DB_NAME` | Postgres / Knowledge | Cloud SQL credentials |
| Application credentials | all GCP agents | Workload Identity / mounted SA key |

Inter-service URLs (orchestrator → agents, UI → orchestrator) should point to
the deployed service hostnames, not `localhost`, once running on the platform.

---

## 8. Verify an image after deploy

Each FastAPI agent exposes `GET /health`:

```bash
curl -s http://<host>:<port>/health        # agents -> {"status":"ok"} style 200
curl -s http://<host>:5000/                 # UI dashboard (HTTP 200)
curl -s http://<host>:5001/                 # STIP Generator (HTTP 200)
```

---

## 9. Security notes

- **Do not commit the Artifactory token** inside the `--index-url`. The current
  Dockerfiles embed it (matching the original sample); before committing to git,
  switch to a BuildKit secret or build `ARG` so the credential is not baked into
  image layers or history. Example:

  ```dockerfile
  # Dockerfile
  ARG PIP_INDEX_URL
  RUN pip install --no-cache-dir --index-url "$PIP_INDEX_URL" -r requirements.txt
  ```

  ```bash
  buildctl ... --opt build-arg:PIP_INDEX_URL="https://<user>:<token>@.../simple" ...
  ```

- Pin images by **digest** (`@sha256:...`) in deployment manifests for
  reproducibility.
- Keep least-privilege service accounts; grant only the GCP roles each agent
  needs (Vertex AI, GCS, Cloud SQL).
