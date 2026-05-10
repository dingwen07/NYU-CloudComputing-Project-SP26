FROM python:3.12-slim

WORKDIR /app
ARG SERVICE_DIR=.

RUN apt-get update && apt-get install -y build-essential libgmp-dev && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

COPY ${SERVICE_DIR}/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY common/ /app/common/
RUN pip install -e /app/common

COPY ${SERVICE_DIR}/src/ /app/src/

EXPOSE 8080
EXPOSE 9000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8080"]
