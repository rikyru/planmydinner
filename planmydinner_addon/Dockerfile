# Dockerfile for Plan My Dinner Add-on
ARG BUILD_FROM
FROM ${BUILD_FROM}

# Set working directory
WORKDIR /usr/src/app

ENV PYTHONPATH=/usr/src/app:${PYTHONPATH}

# Copy the requirements file
COPY requirements.txt ./

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Expose the port the app runs on
EXPOSE 8000

# Command to run the application
CMD [ "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000" ]
