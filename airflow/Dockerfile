FROM apache/airflow:2.10.5

# Create models directory and set ownership
USER root
RUN mkdir -p /app/models

USER airflow
# Copy the requirements.txt
COPY requirements.txt /tmo/requirements.txt

# Install pip install -r requirements.txt
RUN pip install -r /tmp/requirements.txt

# Switch back to airflow user for safety
USER airflow