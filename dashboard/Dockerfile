FROM python:3.9-slim

WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy the test script and dashboard app
COPY app.py .
COPY ../test_email_intelligence.py /app/test_email_intelligence.py

# Expose port for Streamlit
EXPOSE 8501

# Command to run the dashboard
ENTRYPOINT ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]