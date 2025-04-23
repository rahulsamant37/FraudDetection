FROM python:3.10.16-slim-bookworm
WORKDIR /app
COPY requirements.txt /app/requirements.txt

## Install dependencies
RUN pip install -r /app/requirements.txt

## Copy the rest of the application
COPY . .

## Set the command to run the application
EXPOSE 5000