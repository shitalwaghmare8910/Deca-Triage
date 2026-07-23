FROM artifactory.sdlc.ctl.gcp.db.com/dkr-public-local/gcp-community-images/python:3.10

# Set workdir inside the container
WORKDIR /app

# Env settings (no .pyc, unbuffered stdout)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/root/.local/bin:/usr/local/bin:$PATH"

# Install Python dependencies
COPY requirements.txt ./

RUN pip install --no-cache-dir --upgrade pip \
&& pip install --no-cache-dir \
       --index-url https://shital.waghmare@db.com:AKCpBuoC85rMevUKvQTev1yALA7G2aygLsytwevvS1pT1vkdaU3iy6V6pRYjHTgnU2A1S557B@artifactory.sdlc.ctl.gcp.db.com/artifactory/api/pypi/pypi/simple \
       -r requirements.txt \
&& echo "PATH is: $PATH"

# Copy application code
COPY . .

# Expose FastAPI port
EXPOSE 8008

# Use uvicorn to run the FastAPI app (module is agent.py -> app)
ENTRYPOINT []
CMD ["python", "-m", "uvicorn", "agent:app", "--host", "0.0.0.0", "--port", "8008"]
