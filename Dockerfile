FROM python:3.12-slim-bookworm

WORKDIR /app

COPY . .

RUN apt update && apt install -y pkg-config libsystemd-dev build-essential
RUN pip install --no-cache-dir -r requirements.txt

CMD ["./run_server.sh"]
EXPOSE 8000
