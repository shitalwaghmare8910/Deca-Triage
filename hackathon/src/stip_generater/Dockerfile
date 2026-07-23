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

# Copy application code (server.py + static assets)
COPY . .

# Expose Flask port
EXPOSE 5001

# STIP Generator is a Flask app started via server.py (binds 0.0.0.0:5001)
ENTRYPOINT []
CMD ["python", "server.py"]
