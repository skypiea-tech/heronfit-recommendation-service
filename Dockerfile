# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Install system dependencies that might be needed by Python packages (if any)
# Example: RUN apt-get update && apt-get install -y --no-install-recommends some-package && rm -rf /var/lib/apt/lists/*
# Add any specific system dependencies here if needed later

# Copy the requirements file into the container at /app
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
# --no-cache-dir reduces image size
# --default-timeout=100 increases timeout for potentially slow installs
RUN pip install --no-cache-dir --default-timeout=100 -r requirements.txt

# Copy the rest of the application code into the container at /app
# Ensure .dockerignore is used if needed to exclude files like .env, venv, .git etc.
COPY . .

# Make port 8080 available to the world outside this container
# Render typically expects services to listen on port 8080 or 10000
EXPOSE 8080

# Define environment variable for the port (optional but good practice)
ENV PORT=8080

# Run app.py when the container launches using Gunicorn
# gunicorn -w 4 -b 0.0.0.0:$PORT app:app
# -w 4: Number of worker processes (adjust based on instance size/load)
# -b 0.0.0.0:$PORT: Bind to all network interfaces on the specified port
# app:app: Look for the Flask app instance named 'app' inside the 'app.py' file
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:8080", "app:app"]
