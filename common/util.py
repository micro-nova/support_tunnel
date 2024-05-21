import logging

from secrets import token_hex as secret_token
from datetime import datetime, timezone, timedelta

from urllib3.util import Retry
from requests import Session
from requests.adapters import HTTPAdapter
from fabric.connection import Connection
from typing import Union, Optional

from common.models import SupportUser
from device.local_context import LocalContext
from common.constants import TUNNEL_EXPIRY_MINS

api = Session()
retries = Retry(
    total=10,
    backoff_factor=2,
    status_forcelist=[500, 502, 503, 504],
    allowed_methods=None,  # TODO: strive towards idempotency
)
api.mount("https://", HTTPAdapter(max_retries=retries))


def create_user(c: Union[LocalContext, Connection], username: Optional[str] = None, username_prefix: str = "support") -> SupportUser:
    """ Creates a user for support to use. """
    logging.debug("creating a user")
    if username:
        name = username
    else:
        name = f"{username_prefix}{secret_token(nbytes=4)}"

    # TODO: better sanitize input
    if not name.isalnum() or not name.isascii():
        raise ValueError("invalid input for user creation")

    c.run(f"sudo useradd -G sudo -s $(which bash) -mU {name}")
    c.run(f"sudo su {name} -c '< /dev/zero ssh-keygen -q -t ed25519 -N \"\" '")
    pubkey = c.run(f"sudo cat /home/{name}/.ssh/id_ed25519.pub")

    assert pubkey  # TODO: do better error checking here. why does mypy think
    # this can eval to Union[Result, Any, None] ?
    return SupportUser(username=name, ssh_pubkey=pubkey.stdout)


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
    c.run(
        f"echo '{authorized_key}' | sudo tee -a /home/{user.username}/.ssh/authorized_keys")
    c.run(
        f"sudo chown {user.username}:{user.username} /home/{user.username}/.ssh/authorized_keys")
    c.run(f"sudo chmod 0600 /home/{user.username}/.ssh/authorized_keys")


def expiry_datetime():
    """ returns a datetime representing an expiry time TUNNEL_EXPIRY_MINS in the the future """
    return datetime.now(timezone.utc) + timedelta(minutes=TUNNEL_EXPIRY_MINS)
