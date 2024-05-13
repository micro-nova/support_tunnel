import json
import random
import logging

from os import getenv
from time import sleep
from functools import cache
from typing import Optional
from datetime import datetime

from pydantic import UUID4
from ipaddress import IPv4Network
from fabric import Connection, task
from google.cloud import secretmanager
from wireguard_tools import WireguardKey
from tenacity import retry, stop_after_attempt, wait_fixed

from common.util import api, create_user
from common.crypto import create_secret_box
from common.constants import INSTANCE_NAME_PREFIX
from admin.cloud import create_ts_instance, list_ts_instances
from common.tunnel import write_wireguard_config, start_wireguard_tunnel, device_ip, server_ip
from common.models import TunnelState, WireguardTunnel, WireguardPeer, TunnelServerLaunchDetails, SupportSecretBoxContents

SUPPORT_TUNNEL_API = getenv(
    "SUPPORT_TUNNEL_API",
    "https://support-tunnel.prod.gcp.amplipi.com"
)

ADMIN_AUTH_TOKEN_NAME = getenv(
    "ADMIN_AUTH_TOKEN_NAME",
    "support-tunnel-admin-token-prod"
)

PROJECT_ID = getenv("PROJECT_ID")
assert PROJECT_ID

DEBUG = getenv("DEBUG", False)  # any value set here will turn on debugging
logging.basicConfig(level=logging.DEBUG if DEBUG else logging.WARNING)


@cache
@retry(stop=stop_after_attempt(5), wait=wait_fixed(2))
def token() -> str:
    """ Gets an API key token from Google Secret Manager, to use to authenticate this service.
        This is nice because we can assume we already have some sort of auth to GCP... but less nice
        because it does not identify a single user, cannot be revoked for a single user, and
        ties us to GCP just a smidge. Opted for this because it's super easy implementation
        and also super easy to rip out in favor of another auth methanism when the day comes.
    """
    sm_client = secretmanager.SecretManagerServiceClient()
    resp = sm_client.access_secret_version(request={
        "name": f"projects/{PROJECT_ID}/secrets/{ADMIN_AUTH_TOKEN_NAME}/versions/latest"
    })
    return resp.payload.data.decode("UTF-8")


def auth_header() -> dict:
    return {'admin-auth-token': token()}


def get_tunnel(tunnel_id) -> Optional[dict]:
    res = api.get(
        f"{SUPPORT_TUNNEL_API}/admin/tunnel/{tunnel_id}", headers=auth_header())
    if res and res.text:
        return json.loads(res.text)
    return None


@task
def get(c, tunnel_id):
    """ Get a single tunnel """
    print(get_tunnel(tunnel_id))


@task
def list(c):
    """ List tunnels from upstream API's db. """
    res = api.get(f"{SUPPORT_TUNNEL_API}/admin/tunnel/list",
                  headers=auth_header())
    res.raise_for_status()
    print(res.text)

# step 2: launch & configure the tunnel server
# step 3: POST details back to the API


@task
def create(c, tunnel_id: UUID4, preshared_key: WireguardKey):
    """ Create a tunnel server.

        This launches a cloud server, configures it using the device's information,
        and posts further configuration data back to the API.
    """
    res = api.get(
        f"{SUPPORT_TUNNEL_API}/admin/tunnel/{tunnel_id}", headers=auth_header())
    res.raise_for_status()
    device_details = json.loads(res.text)
    assert device_details['state'] != 'completed', "Tunnel has completed. Please create a new tunnel."
    assert device_details['state'] != 'timedout', "Tunnel has timed out. Please create a new tunnel."

    # Create the cloud instance
    i = create_ts_instance(tunnel_id)
    # and wait a bit for SSH to come up. This would be nice:
    # https://github.com/fabric/fabric/issues/1808
    sleep(60)  # seconds

    # Create our wireguard primitives
    device_peer = WireguardPeer(
        public_key=device_details['device_wg_public_key'],
        allowed_ip=device_ip(
            IPv4Network(device_details['network'])
        )
    )
    private_key = WireguardKey.generate()
    t = WireguardTunnel(
        interface=f"support-{random.randint(10,9999)}",
        private_key=private_key,
        public_key=private_key.public_key(),
        my_ip=server_ip(
            IPv4Network(device_details['network'])
        ),
        network=IPv4Network(device_details['network']),
        preshared_key=WireguardKey(preshared_key),
        # the below port range is also defined in the firewall rules for the hosts
        # in opentofu
        port=random.randint(20000, 65534),
        peers=[device_peer]
    )

    c = Connection(i.public_ips[0])

    # Configure the cloud instance's tunnel
    write_wireguard_config(t, c)

    # and start the tunnel
    start_wireguard_tunnel(t, c)

    # create a user on the tunnel server
    u = create_user(c, username="support")

    # create a b64 secretbox with the ssh public key in it
    plaintext = SupportSecretBoxContents(
        support_ssh_pubkey=u.ssh_pubkey).model_dump_json()
    sb = create_secret_box(
        str(t.private_key), device_details['device_wg_public_key'], plaintext)

    # Send our details back to the API
    post_data = TunnelServerLaunchDetails(
        tunnel_id=tunnel_id,
        ts_instance_id=i.id,
        ts_public_ip=i.public_ips[0],
        ts_wg_public_key=str(t.public_key),
        ts_wg_port=t.port,
        support_secret_box=sb
    ).model_dump_json()

    res = api.post(f"{SUPPORT_TUNNEL_API}/admin/tunnel/details",
                   data=post_data, timeout=60, headers=auth_header())
    res.raise_for_status()


@task
def gc(c):
    """ Garbage collect all resources. """
    # TODO: actually cast things into a model for this response
    res = api.get(f"{SUPPORT_TUNNEL_API}/admin/tunnel/list",
                  headers=auth_header(), timeout=60)
    res.raise_for_status()
    all_tunnels = json.loads(res.text)

    # find all things expired but not stopped, and stop them
    for t in all_tunnels:
        if datetime.fromisoformat(t['expires']) < datetime.now() and t.status not in [TunnelState.completed, TunnelState.timedout]:
            print(
                f"tunnel {t['tunnel_id']} expired {t['expires']}; updating API.")
            api.delete(
                f"{SUPPORT_TUNNEL_API}/admin/tunnel/{t['tunnel_id']}", headers=auth_header(), timeout=60)

    # find all server resources not associated with a running Tunnel
    running_nodes = list_ts_instances()
    for n in running_nodes:
        tunnel_id = n.name.removeprefix(f"{INSTANCE_NAME_PREFIX}-")
        t = get_tunnel(tunnel_id)
        if not t or t['state'] in [TunnelState.completed, TunnelState.timedout]:
            print(
                f"tunnel {tunnel_id} still has running resources. destroying {n.id}")
            n.destroy()


@task
def stop(c, tunnel_id):
    """ Stops a single tunnel. """
    res = api.delete(f"{SUPPORT_TUNNEL_API}/admin/tunnel/{tunnel_id}",
                     headers=auth_header(), timeout=60)
    res.raise_for_status()
    # being lazy and overzealous at the same time - we'll just garbage-college its resources.
    gc(c)
