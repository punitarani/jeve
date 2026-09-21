"""Entry point for the jeve API application.

This is a thin wrapper that imports and runs the FastAPI app from the main jeve package.
The actual API code remains in py/src/jeve/api/ to maintain the single distribution approach.
"""

import sys
from pathlib import Path

# Add the main jeve package to the path
jeve_src = Path(__file__).parent.parent.parent / "py" / "src"
sys.path.insert(0, str(jeve_src))

from jeve.api.app import app

def main():
    """Run the FastAPI API server."""
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)

if __name__ == "__main__":
    main()