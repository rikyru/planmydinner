#!/usr/bin/env bash
set -e

CONFIG_PATH=/data/options.json
DB_PATH=$(jq --raw-output ".db_path" $CONFIG_PATH)

echo "Starting Plan My Dinner Add-on"
echo "Database will be stored at: ${DB_PATH}"

# Run the FastAPI server
exec uvicorn main:app --host 0.0.0.0 --port 8000
