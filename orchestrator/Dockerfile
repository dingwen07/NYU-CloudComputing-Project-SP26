FROM python:3.12-slim

WORKDIR /app
ARG SERVICE_DIR=.

COPY ${SERVICE_DIR}/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY common/ /app/common/
RUN pip install -e /app/common

COPY ${SERVICE_DIR}/src/ /app/src/
COPY service-account.json /app/service-account.json

EXPOSE 8080

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8080"]
