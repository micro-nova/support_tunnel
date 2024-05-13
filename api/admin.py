from os import getenv
from typing import Sequence
from datetime import datetime
from hmac import compare_digest

from pydantic import UUID4
from ipaddress import IPv4Address
from sqlmodel import Session, select
from fastapi.security import APIKeyHeader
from fastapi import APIRouter, Depends, HTTPException, status

from api.utils import get_tunnel
from api.models import engine, Tunnel
from common.models import TunnelState, TunnelServerLaunchDetails


ENV = getenv("ENV")
assert ENV

ADMIN_AUTH_TOKEN = getenv("ADMIN_AUTH_TOKEN")
assert ADMIN_AUTH_TOKEN

base_header_scheme = APIKeyHeader(name="admin-auth-token")


def auth(token: str = Depends(base_header_scheme)):
    no = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    if not ADMIN_AUTH_TOKEN:
        raise no
    if not token:
        raise no
    if compare_digest(ADMIN_AUTH_TOKEN, token):
        return token
    raise no


# The below router is used for all communication from the administrators of the service.
admin = APIRouter(prefix="/admin", dependencies=[Depends(auth)])


@admin.get('/tunnel/list')
# TODO: make a redacted return type for this
def list_tunnels() -> Sequence[Tunnel]:
    with Session(engine) as sesh:
        q = select(Tunnel)
        tunnels = sesh.exec(q).all()
        return tunnels


@admin.get("/tunnel/{tunnel_id}")
def get_one_tunnel(tunnel_id: UUID4) -> Tunnel:
    with Session(engine) as sesh:
        return get_tunnel(tunnel_id, sesh)


@admin.post('/tunnel/details')
def post_tunnel_details(req: TunnelServerLaunchDetails):
    with Session(engine) as sesh:
        t = get_tunnel(req.tunnel_id, sesh)
        # I'd like to live in a locked down world where we only accept new details
        # for tunnels that are in the pending state. However, that doesn't match the reality -
        # tunnel servers sometimes need to be kicked off again, sometimes requests fail, etc.
        # We'll instead just assert that the tunnel is not explicitly closed.
        # TODO: handle this case better.
        # TODO: don't use an assert here
        # assert t.state == TunnelState.pending
        assert t.state != TunnelState.completed
        assert t.state != TunnelState.timedout
        t.ts_instance_id = req.ts_instance_id
        t.ts_public_ip = str(IPv4Address(req.ts_public_ip))  # type: ignore
        t.ts_wg_public_key = req.ts_wg_public_key
        t.ts_wg_port = req.ts_wg_port
        t.state = TunnelState.started
        t.support_secret_box = req.support_secret_box
        sesh.add(t)
        sesh.commit()


@admin.delete('/tunnel/{tunnel_id}')
def stop_tunnel(tunnel_id: UUID4):
    """ Sets the tunnel state to "completed" """
    with Session(engine) as sesh:
        t = get_tunnel(tunnel_id, sesh)
        if t.expires < datetime.now():
            t.state = TunnelState.timedout
        else:
            t.state = TunnelState.completed
        sesh.add(t)
        sesh.commit()
