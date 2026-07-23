# NOTE: Build this image from the PROJECT ROOT (build context = repo root),
# because this agent imports the shared package `src.common.db_connection`.
#
#   export IMAGE_URI="artifactory.sdlc.ctl.gcp.db.com/dkr-all/com/db/aiplatform/apps/knowledge-ingestion:0.1.0"
#   buildctl --addr tcp://buildkitd.buildkit.svc.cluster.local:1234 build \
#     --frontend dockerfile.v0 \
#     --local context=. \
#     --local dockerfile=src/agents/knowledge_ingestion \
#     --output type=image,name=$IMAGE_URI,push=true

FROM artifactory.sdlc.ctl.gcp.db.com/dkr-public-local/gcp-community-images/python:3.10

# Set workdir inside the container
WORKDIR /app

# Env settings (no .pyc, unbuffered stdout). PYTHONPATH lets `from src.common...` resolve.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    PATH="/root/.local/bin:/usr/local/bin:$PATH"

# Install Python dependencies (paths are relative to the repo-root build context)
COPY src/agents/knowledge_ingestion/requirements.txt ./

RUN pip install --no-cache-dir --upgrade pip \
&& pip install --no-cache-dir \
       --index-url https://shital.waghmare@db.com:AKCpBuoC85rMevUKvQTev1yALA7G2aygLsytwevvS1pT1vkdaU3iy6V6pRYjHTgnU2A1S557B@artifactory.sdlc.ctl.gcp.db.com/artifactory/api/pypi/pypi/simple \
       -r requirements.txt \
&& echo "PATH is: $PATH"

# Shared package required by the agent (src/common/db_connection.py)
COPY src/__init__.py ./src/__init__.py
COPY src/common ./src/common

# Agent application code -> /app (agent.py becomes /app/agent.py)
COPY src/agents/knowledge_ingestion/ ./

# Expose FastAPI port
EXPOSE 8001

# Use uvicorn to run the FastAPI app (module is agent.py -> app)
ENTRYPOINT []
CMD ["python", "-m", "uvicorn", "agent:app", "--host", "0.0.0.0", "--port", "8001"]
