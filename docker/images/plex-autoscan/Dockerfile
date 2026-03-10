FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ .

ENV PLEX_AUTOSCAN_CONFIG=/config/config.json

EXPOSE 3468

CMD ["python", "scan.py", "server"]
