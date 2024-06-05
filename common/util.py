import logging
import configparser

from os import getenv
from pathlib import Path
from functools import lru_cache
from secrets import token_hex as secret_token
from datetime import datetime, timezone, timedelta

from urllib3.util import Retry
from requests import Session
from requests.adapters import HTTPAdapter
from fabric.connection import Connection
from typing import Union, Optional

from common.models import SupportUser
from device.local_context import LocalContext
from common.constants import TUNNEL_EXPIRY_MINS, SSH_KEYFILE_PATH

api = Session()
retries = Retry(
    total=10,
    backoff_factor=2,
    status_forcelist=[500, 502, 503, 504],
    allowed_methods=None,  # TODO: strive towards idempotency
)
api.mount("https://", HTTPAdapter(max_retries=retries))

def create_group(c: Union[LocalContext, Connection], group_name: str = "support"):
    """ Creates a group for the support user(s). """
    logging.debug(f"creating a Unix group: {group_name}")
    # -f allows this command to complete successfully if this group already exists.
    # We do not clean this group up on tunnel teardown, lest other concurrent tunnels
    # exist.
    c.run(f"sudo groupadd -f {group_name}")

def create_sshkey(c: Union[LocalContext, Connection], dest: Path = SSH_KEYFILE_PATH) -> str:
    """ Creates an SSH pub/priv keypair and places them at the specified destination. Returns the pubkey"""
    c.run(f"sudo mkdir -p {str(dest.parent)}")
    c.run(f"sudo chmod 0777 {str(dest.parent)}")
    c.run(f"< /dev/zero ssh-keygen -q -t ed25519 -N \"\" -f {str(dest)}")
    c.run(f"chmod 0666 {str(dest)}*") #TODO: tighten this up. May involve significant changes in how we tunnel
    pubkey = c.run(f"cat {str(dest)}.pub")
    assert pubkey
    return pubkey.stdout

def create_user(c: Union[LocalContext, Connection], username: Optional[str] = None, username_prefix: str = "support", group_name: str = "support") -> SupportUser:
    """ Creates a user for support to use. """
    logging.debug("creating a Unix user")
    if username:
        name = username
    else:
        name = f"{username_prefix}{secret_token(nbytes=4)}"

    # TODO: better sanitize input
    if not name.isalnum() or not name.isascii():
        raise ValueError(f"invalid input for user creation: {name}")

    # Because we have an explicit dependency on the specified group existing, we call create_group() here.
    create_group(c)

    c.run(f"sudo useradd -g {group_name} -s $(which bash) -m {name}")

    return SupportUser(username=name, group=group_name)


def delete_user(c: Union[LocalContext, Connection], username: str):
    """ Deletes a user. """
    logging.debug(f"deleting user {username}")

    # TODO: better sanitize input
    if not username.isalnum() or not username.isascii():
        raise ValueError("invalid input for user deletion")

    # Should we remove the support user's homedir? I've opted to do so, but
    # the case could be made to keep this data intact for future troubleshooting.
    c.run(f"sudo userdel -rf {username}", warn=True)


def add_authorized_key(c: Union[LocalContext, Connection], user: SupportUser, authorized_key: str):
    """ Add an authorized key to a user. """
    c.run(f"sudo mkdir -p /home/{user.username}/.ssh")
    c.run(
        f"echo '{authorized_key}' | sudo tee -a /home/{user.username}/.ssh/authorized_keys")
    c.run(
        f"sudo chown {user.username}:{user.group} /home/{user.username}/.ssh/authorized_keys")
    c.run(f"sudo chmod 0600 /home/{user.username}/.ssh/authorized_keys")


def expiry_datetime():
    """ returns a datetime representing an expiry time TUNNEL_EXPIRY_MINS in the the future """
    return datetime.now(timezone.utc) + timedelta(minutes=TUNNEL_EXPIRY_MINS)

def _project_id_from_gcloud_conf(conf_file: Path = Path.home() / Path(".config/gcloud/configurations/config_default")) -> str:
    """ Gets the GCP project id from a local `gcloud` configuration. """
    config = configparser.ConfigParser()
    with open(conf_file, 'rt') as c:
        config.read_file(c)
    return config.get('core', 'project')

@lru_cache(1)
def project_id() -> str:
    """ Gets the GCP project ID from either an env var, or a local gcloud configuration """
    try:
        p = getenv("PROJECT_ID")
        if not p:
            p = _project_id_from_gcloud_conf()
        assert p
    except Exception as e:
        logging.error("No usable GCP project ID found. Set the env var PROJECT_ID, or ensure your default `gcloud` configuration is valid.")
        raise e
    return p
