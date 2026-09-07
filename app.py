import uvicorn
from backend.main import app

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8989))
    uvicorn.run("backend.main:app", host="0.0.0.0", port=port)
