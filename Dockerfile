FROM python:3.12-slim

# Create a non-root user to run the application
RUN groupadd --gid 1000 appgroup \
    && useradd --uid 1000 --gid appgroup --no-create-home --shell /bin/bash appuser

WORKDIR /app

# Install Python dependencies (done as root so pip can write to /usr/local)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY app/ ./app/
COPY pyproject.toml ./
COPY migrations/ ./migrations/
COPY prompts/ ./prompts/
COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh

# Hand ownership to the non-root user
RUN chown -R appuser:appgroup /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://localhost:{os.environ.get(\"PORT\",\"8000\")}/api/health').read()"

ENTRYPOINT ["./entrypoint.sh"]
