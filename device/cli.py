import json
import random
import logging

from jose import jwt
from os import getenv
from time import sleep
from datetime import datetime

from invoke import task
from pydantic import UUID4
from requests import HTTPError
from sqlmodel import Session, select
from wireguard_tools import WireguardKey

from common.crypto import open_secret_box
from device.local_context import LocalContext
from device.models import DeviceTunnel, engine
from common.exceptions import TunnelExpiredException
from common.util import api, create_user, delete_user, add_authorized_key
from common.tunnel import allocate_address_space, write_wireguard_config, start_wireguard_tunnel
from common.models import TunnelRequest, TunnelRequestTokenData, Token, TunnelServerLaunchDetailsResponse, DeviceTunnelLaunchDetails, TunnelState

SUPPORT_TUNNEL_API = getenv(
    "SUPPORT_TUNNEL_API",
    "https://support-tunnel.prod.gcp.amplipi.com/v1/"
)

# How long to wait for a tunnel approval
TS_WAIT_TIME_SECONDS = int(getenv("TS_WAIT_TIME_SECONDS", 250))

DEBUG = getenv("DEBUG", False)  # any value set here will turn on debug

logging.basicConfig(level=logging.DEBUG if DEBUG else logging.WARNING)


def get_device_tunnel(tunnel_id: UUID4, sesh: Session) -> DeviceTunnel:
    """ Utility function to return a device tunnel instance from the DB """
    stmt = select(DeviceTunnel).where(DeviceTunnel.tunnel_id == tunnel_id)
    return sesh.exec(stmt).one()


@task
def request(c) -> UUID4:
    """ Request a support tunnel

        Requests a support tunnel from the API, and stashes details about it in the DB.

        Returns the tunnel_id.
    """
    logging.info("generating wireguard keys & allocating address space.")
    device_wg_private_key = WireguardKey.generate()
    device_wg_public_key = device_wg_private_key.public_key()
    network = allocate_address_space()

    logging.info(f"sending tunnel request to {SUPPORT_TUNNEL_API}")
    post_data = TunnelRequest(
        device_wg_public_key=str(device_wg_public_key),
        network=network
    ).model_dump_json()
    logging.debug(f"post_data: {post_data}")
    try:
        res = api.post(
            f"{SUPPORT_TUNNEL_API}/device/tunnel/request", data=post_data, timeout=60)
        res.raise_for_status()
    except HTTPError as e:
        logging.error(f"{res.reason}: {res.text}")
        raise e

    # We get a jwt back from the server; this identifies our session.
    token = Token(**json.loads(res.text))
    loaded_response = TunnelRequestTokenData(
        **jwt.get_unverified_claims(token.access_token))

    # TODO: better data validation here; perhaps make these two derived values/methods off the token
    # removeprefix() was introduced in Python 3.9; uncomment this when we upgrade on AmpliPi
    # tunnel_id = loaded_response.sub.removeprefix("tunnel_id:")
    tunnel_id = loaded_response.sub[len("tunnel_id:"):]
    expires = datetime.fromtimestamp(loaded_response.exp)
    logging.debug(f"tunnel_id: {tunnel_id}, expires: {expires}")

    # last bits of config
    # wireguard preshared keys take the exact format as private keys
    # ref: https://git.zx2c4.com/wireguard-tools/tree/src/wg.c?id=13f4ac4cb74b5a833fa7f825ba785b1e5774e84f#n27
    logging.info("generating preshared key, port, interface")
    wg_preshared_key = str(WireguardKey.generate())
    interface = f"support-{random.randint(10,99999)}"
    port = random.randint(20000, 65534)

    logging.info(
        "creating a DeviceTunnel instance and saving it to the database")
    t = DeviceTunnel(
        tunnel_id=tunnel_id,
        interface=interface,
        device_wg_public_key=str(device_wg_public_key),
        device_wg_private_key=str(device_wg_private_key),
        wg_preshared_key=wg_preshared_key,
        token=token.access_token,
        expires=expires,
        network=str(network),
        port=port
    )
    with Session(engine) as sesh:
        sesh.add(t)
        sesh.commit()
        print(f"tunnel_id: {t.tunnel_id}")
        print(f"preshared_key: {wg_preshared_key}")
        return t.tunnel_id


def get_tunnel_details(tunnel: DeviceTunnel) -> TunnelServerLaunchDetailsResponse:
    """ Utility function to request tunnel details from upstream """
    logging.info(f"get_tunnel_details() called for {tunnel.tunnel_id}")
    headers = {"Authorization": f"Bearer {tunnel.token}"}
    res = api.get(f"{SUPPORT_TUNNEL_API}/device/tunnel/details",
                  headers=headers, timeout=60)
    res.raise_for_status()
    logging.debug(f"get_tunnel_details: {res.text}")
    return TunnelServerLaunchDetailsResponse(**json.loads(res.text))

# step 6: req tunnel details based on tunnel id
# This step is necessary so the device can get the tunnel server's public IP, public key and port.


def request_tunnel_details(tunnel_id: UUID4):
    """ Request tunnel details. This will loop until the tunnel is approved and instantiated, or expired."""
    with Session(engine) as sesh:
        t = get_device_tunnel(tunnel_id, sesh)
        tunnel_details = get_tunnel_details(t)
        while True:
            # At the very most, the tunnel should expire when the JWT the server hands out expires.
            if t.expires < datetime.now():
                msg = "Tunnel has expired."
                logging.warn(msg)
                raise TunnelExpiredException(msg)
            if tunnel_details.state in [TunnelState.completed, TunnelState.timedout]:
                msg = f"API reported the tunnel has ended. state: {tunnel_details.state}"
                logging.warn(msg)
                raise TunnelExpiredException(msg)
            if tunnel_details.state == TunnelState.running or tunnel_details.state == TunnelState.started:
                logging.info("tunnel server running.")
                logging.debug(f"tunnel_details: {tunnel_details}")
                break
            logging.info(
                f"tunnel server not ready. status: {tunnel_details.state}. waiting {TS_WAIT_TIME_SECONDS}s...")
            sleep(TS_WAIT_TIME_SECONDS)
            tunnel_details = get_tunnel_details(t)

    # At this point, the tunnel server has communicated back. We should have all the following
    # in the API's database; assert that our response from the API has actually given us this.
    assert tunnel_details.ts_wg_public_key
    assert tunnel_details.ts_public_ip
    assert tunnel_details.ts_wg_port
    assert tunnel_details.support_secret_box

    with Session(engine) as sesh:
        t = get_device_tunnel(tunnel_id, sesh)
        t.ts_wg_public_key = tunnel_details.ts_wg_public_key
        # We want to be explicit about checking our inputs as ipv4... but for whatever reason
        # the AutoString type doesn't compute this correctly and sqlite complains. We'll cast
        # and tell mypy we know better.
        t.ts_public_ip = str(tunnel_details.ts_public_ip)  # type: ignore
        t.ts_wg_port = tunnel_details.ts_wg_port
        t.support_secret_box = tunnel_details.support_secret_box
        sesh.add(t)
        sesh.commit()

# step 8: send details indicating tunnel is instantiated


def send_connected_status_to_api(t: DeviceTunnel):
    """ Send connection details back to API. """
    post_data = DeviceTunnelLaunchDetails(**t.dict())
    auth_headers = {"Authorization": f"Bearer {t.token}"}
    res = api.post(f"{SUPPORT_TUNNEL_API}/device/tunnel/details",
                   json=post_data.dict(), headers=auth_headers, timeout=60)
    res.raise_for_status()

# step 7: establish wg tunnel to tunnel server


@task
def connect(original_context, tunnel_id: UUID4):  # inv CLI cannot provide UUID4s
    """ Creates a support user and connects to the specified tunnel
        over Wireguard. We use two SQL sessions here in case we end up
        bailing halfway through, and need to clean up user accounts later.
    """
    # create our own local context; this permits us to `.put` on localhost,
    # without using Fabric.
    c = LocalContext(original_context)

    # Get tunnel server details from upstream. This will have the tunnel server's
    # public key, public ip, port, etc.
    try:
        request_tunnel_details(tunnel_id)
    except Exception:
        logging.error("cannot request tunnel details; stopping.")
        stop(c, tunnel_id)
        return 1  # TODO: do something better here

    # Begin spinning up all our local config. Create a user.
    try:
        user = create_user(c)
        with Session(engine) as sesh:
            t1 = get_device_tunnel(tunnel_id, sesh)
            t1.support_user = user.username
            sesh.add(t1)
            sesh.commit()

            assert t1.ts_wg_public_key
            # configure user from secretbox data
            sb = open_secret_box(
                t1.device_wg_private_key,
                t1.ts_wg_public_key,
                t1.support_secret_box
            )
            add_authorized_key(c, user, sb.support_ssh_pubkey)

        # ... and finally write our tunnel config and start it.
        with Session(engine) as sesh:
            t2 = get_device_tunnel(tunnel_id, sesh)

            # create our config
            write_wireguard_config(t2.to_WireguardTunnel(), c)

            # and start it
            start_wireguard_tunnel(t2.to_WireguardTunnel(), c)

            t2.state = TunnelState.running
            sesh.add(t2)
            sesh.commit()
            sesh.refresh(t2)

            # Let upstream know.
            send_connected_status_to_api(t2)

    except Exception as e:
        logging.error(f"unexpected error: {e}")
        logging.warning("cleaning up resources...")
        stop(c, tunnel_id)
        raise e

# step 9: teardown


@task
def stop(c, tunnel_id: UUID4, tunnel_state: TunnelState = TunnelState.completed):
    """ Stops & cleans up device-side resources associated with a tunnel """
    with Session(engine) as sesh:
        t = get_device_tunnel(tunnel_id, sesh)

        if t.support_user:
            delete_user(c, t.support_user)

        if t.interface:
            c.run(f"sudo systemctl stop wg-quick@{t.interface}", warn=True)
            c.run(f"sudo systemctl disable wg-quick@{t.interface}", warn=True)
            c.run(f"sudo rm -f /etc/wireguard/{t.interface}.conf", warn=True)

        t.state = tunnel_state
        t.stopped_at = datetime.now()
        sesh.add(t)
        sesh.commit()

        # Let upstream know.
        # TODO: let upstream know the tunnel_state too
        auth_headers = {"Authorization": f"Bearer {t.token}"}
        res = api.delete(
            f"{SUPPORT_TUNNEL_API}/device/tunnel/delete", headers=auth_headers, timeout=60)
        res.raise_for_status()


@task
def request_and_connect(c):
    """ Request a support tunnel, and wait until connected. """
    print("requesting a tunnel...")
    tunnel_id = request(c)
    print("connecting...")
    connect(c, tunnel_id)


@task
def list_all_tunnels(c):
    """ Lists all tunnel IDs in the local database. Returns a tunnel ID per line. """
    with Session(engine) as sesh:
        stmt = select(DeviceTunnel)
        raw_tunnels = sesh.exec(stmt).all()
        for t in raw_tunnels:
            print(f"{t.tunnel_id}")


@task
def list_running_tunnels(c):
    """ Lists all tunnels whose state is not completed or timedout. """
    with Session(engine) as sesh:
        stmt = select(DeviceTunnel)\
            .where(DeviceTunnel.state != TunnelState.completed)\
            .where(DeviceTunnel.state != TunnelState.timedout)
        tunnels = sesh.exec(stmt).all()
        for t in tunnels:
            print(f"{t.tunnel_id} {t.state}")


@task
def detail_all_tunnels(c):
    """ Dumps all tunnel details in the local database. Returns JSON. """
    # This is a hack; Pydantic is capable of serializing more things than
    # json.dumps(), btu because we can only dump one thing at a time
    # we cast back & forth to produce raw JSON to the console.
    with Session(engine) as sesh:
        stmt = select(DeviceTunnel)
        raw_tunnels = sesh.exec(stmt).all()
        tunnels = []
        for t in raw_tunnels:
            tunnels.append(json.loads(t.model_dump_json()))
        print(json.dumps(tunnels))


@task
def gc(c):
    """ Garbage collects all resources associated with old tunnels. """
    with Session(engine) as sesh:
        stmt = select(DeviceTunnel).where(
            DeviceTunnel.expires < datetime.now())
        tunnels = sesh.exec(stmt).all()
        for t in tunnels:
            stop(c, t.id, TunnelState.timedout)
