import io
import json
import random
import logging

from os import getenv
from uuid import UUID
from time import sleep
from typing import Optional
from datetime import datetime
from functools import lru_cache

from pydantic import UUID4
from paramiko.ed25519key import Ed25519Key
from ipaddress import IPv4Network
from fabric import Connection, task
from google.cloud import secretmanager
from wireguard_tools import WireguardKey
from tenacity import retry, stop_after_attempt, wait_fixed

from common.crypto import create_secret_box
from common.util import api, project_id, create_sshkey
from common.constants import INSTANCE_NAME_PREFIX, SSH_KEYFILE_PATH
from common.tunnel import write_wireguard_config, start_wireguard_tunnel, device_ip, server_ip
from admin.cloud import create_ts_instance, list_ts_instances, get_ts_instance_public_ip, destroy_ts_resources
from common.models import TunnelState, WireguardTunnel, WireguardPeer, TunnelServerLaunchDetails, SupportSecretBoxContents

SUPPORT_TUNNEL_API = getenv(
    "SUPPORT_TUNNEL_API",
    "https://support-tunnel.prod.gcp.amplipi.com/v1"
)

ADMIN_AUTH_TOKEN_NAME = getenv(
    "ADMIN_AUTH_TOKEN_NAME",
    "support-tunnel-admin-token-prod"
)

PROJECT_ID = project_id()

DEBUG = getenv("DEBUG", False)  # any value set here will turn on debugging
logging.basicConfig(level=logging.DEBUG if DEBUG else logging.WARNING)


@lru_cache(1)
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
    t = get_tunnel(tunnel_id)
    print(json.dumps(t))


@task
def list(c):
    """ List tunnels from upstream API's db. """
    res = api.get(f"{SUPPORT_TUNNEL_API}/admin/tunnel/list",
                  headers=auth_header())
    res.raise_for_status()
    print(res.text)

@task
def create(c, tunnel_id: Optional[UUID4] = None, preshared_key: Optional[WireguardKey] = None):
    """ Create a tunnel server.

        This launches a cloud server, configures it using the device's information,
        and posts further configuration data back to the API.
    """
    try:
        if not tunnel_id:
            tunnel_id = UUID(input('tunnel id: ').strip())
        if not preshared_key:
            preshared_key = WireguardKey(input('preshared key: ').strip())
    except Exception as e:
        logging.exception(f"could not use the supplied inputs: {str(e)}")
        return 1

    res = api.get(
        f"{SUPPORT_TUNNEL_API}/admin/tunnel/{tunnel_id}", headers=auth_header())
    res.raise_for_status()
    device_details = json.loads(res.text)
    assert device_details['state'] < TunnelState.completed, "Tunnel has completed. Please create a new tunnel."

    # Create the cloud instance
    print("creating a tunnel server")
    i = create_ts_instance(tunnel_id)
    # and wait a bit for SSH to come up. This would be nice:
    # https://github.com/fabric/fabric/issues/1808
    sleep(60)  # seconds

    try:
        # Create our wireguard primitives
        device_peer = WireguardPeer(
            public_key=WireguardKey(device_details['device_wg_public_key']),
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

        print("configuring tunnel server")
        ts = Connection(str(get_ts_instance_public_ip(tunnel_id)), connect_timeout=180)

        # things get hacky when being concerned with local ssh keys and all - 
        # the below configures things to "just work", every time.
        c.run("gcloud compute config-ssh", hide="both")
        user_from_oslogin = c.run("gcloud compute os-login describe-profile --format=json", hide="both")
        ts.user = json.loads(user_from_oslogin.stdout)['posixAccounts'][0]['username']

        # Configure the cloud instance's tunnel
        write_wireguard_config(ts, t)

        # and start the tunnel
        start_wireguard_tunnel(ts, t)

        # create our shared ssh key
        ssh_pubkey = create_sshkey(ts)

        # create a b64 secretbox with the ssh public key in it
        # using a secretbox, encrypted with this TS's privkey and the device's pubkey,
        # ensures it only could have come from here. (why not a signature instead?
        # pynacl implementation details, mostly.)
        plaintext = SupportSecretBoxContents(
            support_ssh_pubkey=ssh_pubkey).model_dump_json()
        sb = create_secret_box(
            str(t.private_key), device_details['device_wg_public_key'], plaintext)

        # Send our details back to the API
        post_data = TunnelServerLaunchDetails(
            tunnel_id=tunnel_id,
            ts_instance_id=str(i.id), # i.id is naturally an int
            ts_public_ip=get_ts_instance_public_ip(tunnel_id),
            ts_wg_public_key=str(t.public_key),
            ts_wg_port=t.port,
            support_secret_box=sb
        ).model_dump_json()

        res = api.post(f"{SUPPORT_TUNNEL_API}/admin/tunnel/details",
                       data=post_data, timeout=60, headers=auth_header())
        res.raise_for_status()

        print("tunnel server created! It may take up to 5 minutes for the remote device to check back in, but when it does you can run the following command to log into it:")
        print(f"fab connect {tunnel_id}")
    except Exception as e:
        logging.exception(f"failed to configure tunnel server: {str(e)}")
        destroy_ts_resources(tunnel_id)
        raise e


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
        if datetime.fromisoformat(t['expires']) < datetime.now() and t['state'] not in [TunnelState.completed, TunnelState.timedout]:
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
                f"tunnel {tunnel_id} may have running resources. destroying instance id {n.id}")
            destroy_ts_resources(tunnel_id)


@task
def stop(c, tunnel_id):
    """ Stops a single tunnel. """
    res = api.delete(f"{SUPPORT_TUNNEL_API}/admin/tunnel/{tunnel_id}",
                     headers=auth_header(), timeout=60)
    res.raise_for_status()
    # being lazy and overzealous at the same time - we'll just garbage-college its resources.
    gc(c)

@task
def connect(c, tunnel_id):
    """ Connect to a remote device, identified by a tunnel. """
    # Care should be exercised here; we're taking data from a remote source and using it to
    # run shell commands. Validate every last bit of data.
    t = get_tunnel(tunnel_id)
    assert TunnelState(t['state']) == TunnelState.running, "Device has not yet connected"
    dip = device_ip(IPv4Network(t['network'])).ip
    assert t['support_user'].isalnum()
    assert t['support_user'].isascii()
    support_user = t['support_user']

    # set up local
    c.run("gcloud compute config-ssh", hide="both")
    user_from_oslogin = c.run("gcloud compute os-login describe-profile --format=json", hide="both")
    ts_user = json.loads(user_from_oslogin.stdout)['posixAccounts'][0]['username']

    # set up connection to bastion
    gw = Connection(
        host = str(get_ts_instance_public_ip(tunnel_id)),
        user = ts_user
    )

    # grab the ssh private key on the tunnel server
    ssh_privkey = gw.run(f"sudo cat {SSH_KEYFILE_PATH}", hide="both")
    assert ssh_privkey

    # set up connection to destination device
    device = Connection(
        host=str(dip),
        user=support_user,
        gateway=gw,
        connect_kwargs = {
            "pkey": Ed25519Key.from_private_key(io.StringIO(ssh_privkey.stdout)),
        }
    )

    # and finally execute a shell
    device.sudo("/bin/bash", pty=True)
