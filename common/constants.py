from os import getenv
from pathlib import Path

TUNNEL_EXPIRY_MINS = int(
    getenv("TUNNEL_EXPIRY_MINS", 60*24*14))  # default is 14 days
INSTANCE_NAME_PREFIX = "support-tunnel"
SSH_KEYFILE_PATH=Path("/var/lib/support_tunnel/ssh_key")
