FROM python:3.10-slim

ENV HOME=/workspace \
    PYTHONUNBUFFERED=1

WORKDIR ${HOME}

RUN apt-get update && \
    apt-get install -y --no-install-recommends git && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENTRYPOINT ["python3.10", "-m", "app"]
