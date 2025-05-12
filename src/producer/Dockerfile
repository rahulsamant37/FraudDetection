FROM python:3.10.16-slim-bookworm

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=UTF-8

WORKDIR /app

# Install system dependencies (ADD libsasl2-dev HERE)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      curl \
      gnupg \
      gcc \
      g++ \
      build-essential \
      python3-dev \
      libssl-dev \
      libsasl2-dev \
      pkg-config \
      && rm -rf /var/lib/apt/lists/*

# Manually install librdkafka with SASL/SSL support
RUN curl -fsSL https://github.com/confluentinc/librdkafka/archive/refs/tags/v2.8.0.tar.gz -o librdkafka.tar.gz && \
    tar -xzf librdkafka.tar.gz && \
    cd librdkafka-2.8.0 && \
    ./configure --enable-ssl --enable-sasl && \
    make && \
    make install && \
    ldconfig && \
    cd .. && \
    rm -rf librdkafka-2.8.0 librdkafka.tar.gz

# Copy requirements and install Python dependencies
COPY ./requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

# Copy application code
COPY . .

# Entrypoint
ENTRYPOINT ["python3", "main.py"]