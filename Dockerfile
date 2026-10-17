# WorkBuddy Multi-Account Reverse Proxy Gateway
ARG BASE_IMAGE=python:3.11-alpine
FROM ${BASE_IMAGE}

# Set environment
ENV PYTHONUNBUFFERED=1     HOST=0.0.0.0     PORT=8788     API_KEY=     TZ=Asia/Shanghai     WB_DATA_ROOT=/app/data     WB_AUTH_MODE=hybrid

WORKDIR /app

# Alpine timezone & certs
RUN apk add --no-cache tzdata ca-certificates &&     cp /usr/share/zoneinfo/${TZ} /etc/localtime &&     echo "${TZ}" > /etc/timezone

# Copy application files (Zero external pip dependencies needed)
COPY wb_proxy.py wb_accounts.py wb_catalog.py wb_fingerprint.py wb_model_registry.py wb_routing.py wb_scheduler.py wb_tasks.py wb_settings.py wb_auth.py wb_tenants.py dashboard.html ./

# Create data directories
RUN mkdir -p /app/accounts /app/usage /app/data && addgroup -S wb && adduser -S -G wb wb && chown -R wb:wb /app

# Volume persistence for credentials and usage logs
VOLUME ["/app/accounts", "/app/usage", "/app/data"]

USER wb

EXPOSE 8788

# Launch proxy in host 0.0.0.0 mode
CMD ["python", "wb_proxy.py", "--host", "0.0.0.0", "--port", "8788"]
