FROM python:3.11-alpine

WORKDIR /app

RUN pip install --no-cache-dir aiohttp

COPY clearsky_snapshot.py .

CMD ["python3", "-u", "/app/clearsky_snapshot.py"]