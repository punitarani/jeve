"""Entry point for the jeve simulation worker.

This is a thin wrapper that imports and runs the simulation from the main jeve package.
The actual simulation code remains in py/src/jeve/sim/ to maintain the single distribution approach.
"""

import sys
from pathlib import Path

# Add the main jeve package to the path
jeve_src = Path(__file__).parent.parent.parent / "py" / "src"
sys.path.insert(0, str(jeve_src))

def main():
    """Run the simulation daemon."""
    import jeve.sim
    jeve.sim.main()

if __name__ == "__main__":
    main()