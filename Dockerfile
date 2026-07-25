FROM python:3.11-slim

WORKDIR /app

# install golive from the local source tree
COPY pyproject.toml README.md ./
COPY golive ./golive
RUN pip install --no-cache-dir .

# persistent data lives under /data (mount a volume there)
ENV GOLIVE_HOME=/data
VOLUME ["/data"]

EXPOSE 8787
CMD ["golive", "serve", "--host", "0.0.0.0", "--port", "8787"]
