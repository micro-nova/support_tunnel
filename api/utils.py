from sqlmodel import Session, select
from pydantic import UUID4

from api.models import Tunnel


def get_tunnel(tunnel_id: UUID4, sesh: Session) -> Tunnel:
    stmt = select(Tunnel).where(Tunnel.tunnel_id == tunnel_id)
    return sesh.exec(stmt).one()
