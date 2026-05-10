FROM python:3.12-slim

WORKDIR /app
ARG SERVICE_DIR=.

# Install Kubo IPFS
RUN apt-get update && apt-get install -y build-essential libgmp-dev wget curl && \
    arch="$(dpkg --print-architecture)" && \
    wget -q "https://dist.ipfs.tech/kubo/v0.32.1/kubo_v0.32.1_linux-${arch}.tar.gz" && \
    tar xf "kubo_v0.32.1_linux-${arch}.tar.gz" && \
    mv kubo/ipfs /usr/local/bin/ && \
    rm -rf kubo "kubo_v0.32.1_linux-${arch}.tar.gz" && \
    apt-get remove -y wget && apt-get autoremove -y && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY ${SERVICE_DIR}/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY common/ /app/common/
RUN pip install -e /app/common

COPY ${SERVICE_DIR}/src/ /app/src/
COPY service-account.json /app/service-account.json
COPY ${SERVICE_DIR}/start.sh /app/start.sh
RUN chmod +x /app/start.sh

EXPOSE 8080
EXPOSE 9000
EXPOSE 4001/tcp
EXPOSE 4001/udp

CMD ["/app/start.sh"]
