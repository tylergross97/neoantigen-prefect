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
    tmux \
    btrfs-progs \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
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

WORKDIR /workspace

# ---------------------------------------------------------------
# 3) Startup script — starts Prefect server on CONNECT_TOOL_PORT
# ---------------------------------------------------------------
RUN printf '#!/bin/bash\n\
PORT=${CONNECT_TOOL_PORT:-4200}\n\
echo "Starting Prefect server on port $PORT"\n\
exec prefect server start --host 0.0.0.0 --port "$PORT"\n\
' > /usr/local/bin/start-prefect.sh && chmod +x /usr/local/bin/start-prefect.sh

# ---------------------------------------------------------------
# 4) Launch via connect-client
# ---------------------------------------------------------------
ENTRYPOINT ["/usr/bin/connect-client", "--entrypoint"]
CMD ["/bin/bash", "/usr/local/bin/start-prefect.sh"]
