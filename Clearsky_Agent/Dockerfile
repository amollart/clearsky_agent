FROM python:3.11-alpine

WORKDIR /app

RUN apk add --no-cache --virtual .build-deps gcc musl-dev libffi-dev \
    && pip install --no-cache-dir aiohttp azure-storage-blob \
    && apk del .build-deps

COPY run.sh .
COPY clearsky_snapshot.py .
RUN chmod +x /app/run.sh

CMD ["/app/run.sh"]
