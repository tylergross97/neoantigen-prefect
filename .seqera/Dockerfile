# ---------------------------------------------------------------
# Neoantigen Prefect Studio
# Boots directly into the Prefect UI (server + dashboard)
#
# Bases on the Seqera Jupyter studio image so connect-client and
# all platform dependencies are pre-configured. Installs Prefect
# on top and overrides the startup command.
# ---------------------------------------------------------------

FROM public.cr.seqera.io/platform/data-studio-jupyter:4.2.5-0.11

LABEL org.opencontainers.image.source="https://github.com/tylergross97/neoantigen-prefect"

# Install Prefect and flow dependencies
RUN python3 -m pip install --no-cache-dir \
    prefect==3.6.22 \
    httpx>=0.27 \
    python-dotenv>=1.0 \
    boto3>=1.34 \
    pydantic>=2.0

# Startup script — start Prefect server on CONNECT_TOOL_PORT
RUN printf '#!/bin/bash\n\
export PREFECT_SERVER_API_HOST=0.0.0.0\n\
export PREFECT_SERVER_API_PORT=${CONNECT_TOOL_PORT:-4200}\n\
echo "Starting Prefect server on port $PREFECT_SERVER_API_PORT"\n\
exec prefect server start\n\
' > /usr/local/bin/start-prefect.sh && chmod +x /usr/local/bin/start-prefect.sh

CMD ["/bin/bash", "/usr/local/bin/start-prefect.sh"]
