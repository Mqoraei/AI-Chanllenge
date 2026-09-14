# Use a small Python image
FROM python:3.12-slim

# Set the working directory
WORKDIR /app

# Copy the dependency file
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the project files
COPY . .

# Run the client
CMD ["python", "main.py"]