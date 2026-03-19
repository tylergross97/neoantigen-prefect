# ---------------------------------------------------------------
# Neoantigen Prefect Studio
# Boots directly into the Prefect UI (server + dashboard)
# ---------------------------------------------------------------

# ---------------------------------------------------------------
# 1) Pull the connect-client binary
# ---------------------------------------------------------------
ARG CONNECT_CLIENT_VERSION=0.9
FROM public.cr.seqera.io/platform/connect-client:${CONNECT_CLIENT_VERSION} AS connect

# ---------------------------------------------------------------
# 2) Build from Python base
# ---------------------------------------------------------------
FROM python:3.11-slim

LABEL org.opencontainers.image.source="https://github.com/tylergross97/neoantigen-prefect"

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install --no-install-recommends -y \
    git \
    curl \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Install Prefect and flow dependencies
RUN pip install --no-cache-dir \
    prefect==3.6.22 \
    httpx>=0.27 \
    python-dotenv>=1.0 \
    boto3>=1.34 \
    pydantic>=2.0

# Copy connect-client from stage 1 and install
COPY --from=connect /usr/bin/connect-client /usr/bin/connect-client
RUN /usr/bin/connect-client --install

ARG CONNECT_CLIENT_VERSION
LABEL io.seqera.connect.version="${CONNECT_CLIENT_VERSION}"

# ---------------------------------------------------------------
# 3) Bake flow source into image
# ---------------------------------------------------------------
COPY neoantigen_flow.py config.py tasks.py seqera_client.py serve_flow.py /app/

ENV PYTHONPATH=/app

WORKDIR /workspace

# ---------------------------------------------------------------
# 4) Startup script
# ---------------------------------------------------------------
RUN printf '#!/bin/bash\n\
export PREFECT_SERVER_API_HOST=0.0.0.0\n\
export PREFECT_SERVER_API_PORT=${CONNECT_TOOL_PORT:-4200}\n\
export PREFECT_UI_API_URL=/api\n\
export PREFECT_API_URL=http://localhost:${CONNECT_TOOL_PORT:-4200}/api\n\
export PYTHONPATH=/app\n\
\n\
echo "Starting Prefect server on port $PREFECT_SERVER_API_PORT"\n\
prefect server start &\n\
SERVER_PID=$!\n\
\n\
echo "Waiting for Prefect server..."\n\
until curl -sf http://localhost:${PREFECT_SERVER_API_PORT}/api/health > /dev/null 2>&1; do\n\
    sleep 2\n\
done\n\
echo "Server ready — registering deployment"\n\
python /app/serve_flow.py > /workspace/neoantigen-prefect-evjnnnoto/serve_flow.log 2>&1 &\n\
SERVE_PID=$!\n\
echo "serve_flow.py started with PID $SERVE_PID"\n\
sleep 10\n\
if kill -0 $SERVE_PID 2>/dev/null; then\n\
    echo "serve_flow.py still running after 10s — deployment registered OK" >> /workspace/neoantigen-prefect-evjnnnoto/serve_flow.log\n\
else\n\
    echo "serve_flow.py EXITED EARLY — check serve_flow.log" \n\
fi\n\
\n\
wait $SERVER_PID\n\
' > /usr/local/bin/start-prefect.sh && chmod +x /usr/local/bin/start-prefect.sh

# ---------------------------------------------------------------
# 5) Launch via connect-client
# ---------------------------------------------------------------
ENTRYPOINT ["/usr/bin/connect-client", "--entrypoint"]
CMD ["/bin/bash", "/usr/local/bin/start-prefect.sh"]
