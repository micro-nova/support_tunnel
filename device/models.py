import datetime
import common.tunnel
import common.models

from os import getenv
from sqlmodel import Field, SQLModel, create_engine
from pydantic import UUID4
from typing import Optional
from ipaddress import IPv4Address, IPv4Network
from wireguard_tools import WireguardKey
from sqlalchemy.types import Text


class DeviceTunnel(SQLModel, table=True):
    """ Represents the database table on a device, where each row
        contains details about one tunnel.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    tunnel_id: UUID4
    token: str
    network: IPv4Network
    port: int
    state: common.models.TunnelState = Field(default='pending')
    interface: str
    support_user: Optional[str]
    device_wg_public_key: str
    device_wg_private_key: str
    wg_preshared_key: str
    ts_wg_public_key: Optional[str]
    ts_public_ip: Optional[IPv4Address]
    ts_wg_port: Optional[int]
    created_at: datetime.datetime = Field(
        default_factory=datetime.datetime.utcnow,
    )
    stopped_at: Optional[datetime.datetime]
    expires: datetime.datetime
    support_secret_box: Optional[str] = Field(sa_type=Text)

    def to_WireguardTunnel(self) -> common.models.WireguardTunnel:
        """ Creates a common.models.WireguardTunnel representation,
            so we can use other common utility functions.
        """
        peers = []
        if self.ts_wg_public_key:
            peers.append(common.models.WireguardPeer(
                public_key=self.ts_wg_public_key,
                allowed_ip=common.tunnel.server_ip(self.network),
                port=self.ts_wg_port,
                public_ip=self.ts_public_ip
            ))

        return common.models.WireguardTunnel(
            interface=self.interface,
            my_ip=common.tunnel.device_ip(self.network),
            network=IPv4Network(self.network),
            port=self.port,
            public_key=WireguardKey(self.device_wg_public_key),
            private_key=WireguardKey(self.device_wg_private_key),
            preshared_key=WireguardKey(self.wg_preshared_key),
            peers=peers,
        )


SQL_URI = getenv("SQL_URI", "sqlite:////var/lib/support_tunnel/device.db")
engine = create_engine(SQL_URI)
SQLModel.metadata.create_all(engine)
