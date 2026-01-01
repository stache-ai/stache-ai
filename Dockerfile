# Stage 1: Build frontend
FROM node:20-alpine AS frontend-builder

WORKDIR /frontend

# Copy frontend package files first (better caching)
COPY frontend/package*.json ./
RUN npm install

# Copy frontend source and build
COPY frontend/ ./
RUN npm run build

# Stage 2: Python backend with static frontend
FROM python:3.11-slim

WORKDIR /app

# Install profile: airgap, aws, minimal, full (default)
ARG INSTALL_PROFILE=full
# Enable OCR support for scanned PDFs (adds ~230MB)
ARG WITH_OCR=true
# Enable document format support (EPUB, DOCX, PPTX)
ARG WITH_DOCUMENTS=true
# Package version to install
ARG STACHE_VERSION=0.1.2

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && if [ "$WITH_OCR" = "true" ]; then \
         apt-get install -y --no-install-recommends ocrmypdf tesseract-ocr; \
       fi \
    && rm -rf /var/lib/apt/lists/*

# Install packages from PyPI based on profile
RUN --mount=type=cache,target=/root/.cache/pip \
    case "$INSTALL_PROFILE" in \
      airgap) \
        echo "Installing airgap profile (qdrant, ollama, mongodb)..." && \
        pip install \
          stache-ai==$STACHE_VERSION \
          stache-ai-qdrant \
          stache-ai-ollama \
          stache-ai-mongodb && \
        if [ "$WITH_OCR" = "true" ]; then pip install stache-ai-ocr; fi && \
        if [ "$WITH_DOCUMENTS" = "true" ]; then pip install stache-ai-documents; fi ;; \
      aws) \
        echo "Installing aws profile (bedrock, s3vectors, dynamodb)..." && \
        pip install \
          stache-ai==$STACHE_VERSION \
          stache-ai-bedrock \
          stache-ai-s3vectors \
          stache-ai-dynamodb && \
        if [ "$WITH_OCR" = "true" ]; then pip install stache-ai-ocr; fi && \
        if [ "$WITH_DOCUMENTS" = "true" ]; then pip install stache-ai-documents; fi ;; \
      minimal) \
        echo "Installing minimal profile (core only)..." && \
        pip install stache-ai==$STACHE_VERSION ;; \
      full|*) \
        echo "Installing full profile (all providers)..." && \
        pip install \
          stache-ai==$STACHE_VERSION \
          stache-ai-qdrant \
          stache-ai-ollama \
          stache-ai-openai \
          stache-ai-anthropic \
          stache-ai-bedrock \
          stache-ai-cohere \
          stache-ai-mixedbread \
          stache-ai-mongodb \
          stache-ai-dynamodb \
          stache-ai-s3vectors \
          stache-ai-redis \
          stache-ai-pinecone && \
        if [ "$WITH_OCR" = "true" ]; then pip install stache-ai-ocr; fi && \
        if [ "$WITH_DOCUMENTS" = "true" ]; then pip install stache-ai-documents; fi ;; \
    esac

# Copy built frontend from stage 1
COPY --from=frontend-builder /frontend/dist /app/static

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run application
CMD ["uvicorn", "stache_ai.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
