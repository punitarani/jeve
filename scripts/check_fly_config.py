"""OPS-0001's confirmation: fly.toml must parse and declare both process groups.

`flyctl config validate` is not usable here — it calls the Fly API and needs
an access token, which a gate job does not have (and should not). What CI can
check offline is structural: the file parses and names the app and the two
process groups the record pins. Real schema validation still happens at
deploy time, where flyctl runs with credentials.
"""

import sys
import tomllib
from pathlib import Path

cfg = tomllib.loads(Path("fly.toml").read_text())
assert cfg["app"] == "jeve-backend", cfg["app"]
assert {"api", "sim"} <= set(cfg["processes"]), sorted(cfg["processes"])
print("fly.toml: app jeve-backend with api+sim process groups")
sys.exit(0)
