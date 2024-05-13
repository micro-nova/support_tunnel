import uuid
import logging

from os import getenv
from uuid import UUID
from datetime import datetime

from fastapi import Depends, APIRouter, HTTPException, status
from fastapi.security import OAuth2AuthorizationCodeBearer
from pydantic import UUID4
from sqlmodel import Session
from jose import JWTError, jwt

from api.utils import get_tunnel
from api.models import engine, Tunnel
from common.util import expiry_datetime
from common.models import TunnelServerLaunchDetailsResponse, TunnelRequest, Token, TunnelRequestTokenData, TunnelState, DeviceTunnelLaunchDetails

JWT_SECRET = getenv("JWT_SECRET")
JWT_ALGO = "HS256"
assert JWT_SECRET

oauth2_scheme = OAuth2AuthorizationCodeBearer(
    tokenUrl="none", authorizationUrl="none")

device = APIRouter(prefix="/device")


def create_oauth_token(tunnel_id: UUID4):
    """ Generates a JWT to use as an OAuth2 bearer token. """
    assert JWT_SECRET
    expire = int(expiry_datetime().timestamp())
    to_encode = TunnelRequestTokenData(
        sub=f"tunnel_id:{tunnel_id}", exp=expire)
    return jwt.encode(to_encode.dict(), JWT_SECRET, algorithm=JWT_ALGO)


def get_tunnel_id(token: str = Depends(oauth2_scheme)) -> UUID:
    """ A FastAPI authentication dependency that produces the tunnel_id.

        The `tunnel_id` is stashed in a claim in a JWT, which is presented back
        to the API when performing functions.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    assert JWT_SECRET
    try:
        payload = TunnelRequestTokenData(
            **jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO]))
        tunnel_id_str = payload.sub.removeprefix("tunnel_id:")
        logging.debug(f"tunnel_id_str: {tunnel_id_str}")
        tunnel_id = UUID(hex=tunnel_id_str)
    except JWTError:
        raise credentials_exception
    # TODO: maybe validate this UUID is actually in the db?
    except Exception as e:
        logging.error(f"unexpected error: {e}")
        raise e
        # raise credentials_exception
    logging.info(f"auth'd as tunnel_id: {tunnel_id}")
    return tunnel_id


# step #1
# This should avoid the JWT auth present elsewhere; it returns the JWT.
@device.post('/tunnel/request')
def request_tunnel(req: TunnelRequest) -> Token:
    """ Request a tunnel. Returns the OAuth2 bearer token, which contains a 
        claim about which tunnel_id this is.
    """
    t = Tunnel(tunnel_id=uuid.uuid4(), **req.dict())
    token = create_oauth_token(t.tunnel_id)
    with Session(engine) as sesh:
        sesh.add(t)
        sesh.commit()
        return Token(access_token=token, token_type="bearer")

# step #5


@device.get('/tunnel/details')
def get_tunnel_details(tunnel_id: UUID4 = Depends(get_tunnel_id)) -> TunnelServerLaunchDetailsResponse:
    """ This endpoint returns tunnel endpoint details to th device
      * tunnel pubkey after service launch
      * tunnel public ip
      * a support-locked secretbox containing an ssh authorized_keys entry
    """
    with Session(engine) as sesh:
        t = get_tunnel(tunnel_id, sesh)
        return TunnelServerLaunchDetailsResponse(**t.dict())

# step #7


@device.post('/tunnel/details')
def set_tunnel_details_from_device(req: DeviceTunnelLaunchDetails, tunnel_id: UUID4 = Depends(get_tunnel_id)):
    """ This endpoint consumes and stores support_user details and tunnel state, sent by device """
    with Session(engine) as sesh:
        t = get_tunnel(tunnel_id, sesh)
        assert t.state == TunnelState.started
        t.support_user = req.support_user
        t.state = TunnelState.running
        sesh.add(t)
        sesh.commit()


@device.delete('/tunnel/delete')
def stop_tunnel(tunnel_id: UUID4 = Depends(get_tunnel_id)):
    """ This endpoint allows a device to terminate its tunnel.

        We do not clean up VM resources here. This API is intended as a bookkeeping
        mechanism only. The Fabric-based admin CLI has a `gc` command for garbage
        collecting; that can be called from cron or a cloud task if one wants. However,
        a device should not be able to terminate cloud resources, which could for
        example be used to erase forensic evidence during an intrusion.
    """

    # TODO: allow a device to set more than just a completed state - for example,
    # if it caught its own timedout sooner than we did.
    with Session(engine) as sesh:
        t = get_tunnel(tunnel_id, sesh)
        t.state = TunnelState.completed
        t.stopped_at = datetime.now()
        sesh.add(t)
        sesh.commit()
