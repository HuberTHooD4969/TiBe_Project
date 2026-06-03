import uvicorn
uvicorn.run("backend_api:app", host="0.0.0.0", port=8000, log_level="warning")
