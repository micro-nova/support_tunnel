from enum import Enum
from typing import Optional, List, Union
from typing_extensions import Annotated
from ipaddress import IPv4Address, IPv4Network, IPv4Interface

from sqlmodel import SQLModel
from sqlmodel._compat import SQLModelConfig
from pydantic import UUID4, field_serializer
from pydantic.functional_validators import AfterValidator
from wireguard_tools import WireguardConfig, WireguardKey


class TunnelState(int, Enum):
    """ Describes a tunnel state. Behind the scenes, this is represented with integers;
        this permits us to ensure we never move backwards in this process with simple
        greater than/less than comparisons.
    """
    pending = 10  # waiting on admin approval
    started = 20  # tunnel server has launched, waiting for device to connect
    running = 30  # device has started a tunnel, created a user and posted these details
    connected = 40  # communications are occurring; TODO: actually set & use this state
    completed = 50  # exited successfully
    timedout = 60  # the tunnel exceeded its maximum lifetime


class WireguardPeer(SQLModel):
    """ This generic class represents a peer, to be used on one side of a wireguard tunnel """
    public_key: Union[str, WireguardKey]
    allowed_ip: Union[IPv4Address, IPv4Network]
    port: Optional[int] = None
    public_ip: Optional[IPv4Address] = None

    model_config = SQLModelConfig(arbitrary_types_allowed=True)
    @field_serializer('public_key')
    def serialize_key(self, k: WireguardKey, _info):
        return str(k)


class WireguardTunnel(SQLModel):
    """ This generic class represents one side of a wireguard tunnel.
    """
    interface: str  # TODO: is this the single reason why we cannot use a WireguardConfig?
    my_ip: IPv4Interface
    network: IPv4Network
    public_key: WireguardKey
    private_key: WireguardKey
    preshared_key: WireguardKey
    port: int
    peers: List[WireguardPeer]

    # The below permits us to use WireguardKey types.
    model_config = SQLModelConfig(arbitrary_types_allowed=True)

    @field_serializer('public_key')
    @field_serializer('private_key')
    @field_serializer('preshared_key')
    def serialize_key(self, k: WireguardKey, _info):
        return str(k)

    def to_WireguardConfig(self) -> WireguardConfig:
        """ Returns this to a generic WireguardConfig """
        c = {
            "private_key": self.private_key,
            "addresses": [self.my_ip],
            "listen_port": self.port,
            "peers": [{
                "public_key": p.public_key,
                "preshared_key": self.preshared_key,
                "endpoint_host": p.public_ip,
                "endpoint_port": p.port,
                "persistent_keepalive": 14,
                "allowed_ips": [self.network]  # TODO: lock this down
            } for p in self.peers]
        }
        return WireguardConfig.from_dict(c)


class TunnelRequest(SQLModel):
    """ Represents the data sent from the device to the API when initially
        requesting a tunnel.
    """
    device_wg_public_key: str  # TODO: make this a WireguardKey
    network: IPv4Network

    # The below permits us to use WireguardKey types.
    # model_config = SQLModelConfig(arbitrary_types_allowed=True)
    # @field_serializer('device_wg_public_key')
    # def serialize_key(self, k: WireguardKey, _info):
    #  return str(k)


class Token(SQLModel):
    access_token: str
    token_type: str


def tunnel_token_subject_validator(t: str) -> str:
    assert t.startswith("tunnel_id:"), "not a valid token subject"
    return t


TunnelTokenSubject = Annotated[str, AfterValidator(
    tunnel_token_subject_validator)]


class TunnelRequestTokenData(SQLModel):
    """ A JWT token """
    sub: TunnelTokenSubject
    exp: int  # this is actually a epoch timestamp


class DeviceTunnelLaunchDetails(SQLModel):
    """ Data sent from the device to the API, indicating its tunnel has launched
        and what support user is being used.
    """
    support_user: str
    state: TunnelState  # success? failure? is this useful?


class TunnelServerLaunchDetails(SQLModel):
    """ Represents the data sent from the support user's CLI to the API
        upon tunnel server launch.
    """
    tunnel_id: UUID4
    ts_wg_public_key: str  # TODO: actually make this a WireguardKey
    ts_wg_port: int
    ts_instance_id: str
    ts_public_ip: IPv4Address
    support_secret_box: str

    # The below permits us to use WireguardKey types.
    model_config = SQLModelConfig(arbitrary_types_allowed=True)

    @field_serializer('ts_wg_public_key')
    def serialize_key(self, k: WireguardKey, _info):
        return str(k)


class TunnelServerLaunchDetailsResponse(SQLModel):
    """ Represents the data fetched from the API by the device, while it's
        polling for the tunnel server to be approved and come online.
    """
    tunnel_id: UUID4
    state: TunnelState
    ts_wg_public_key: Optional[str]
    ts_wg_port: Optional[int]
    ts_public_ip: Optional[IPv4Address]
    support_secret_box: Optional[str]


class SupportSecretBoxContents(SQLModel):
    """ Represents the contents of the secret box. Largely used to ensure that
        this data is somewhat sanitized.
    """
    support_ssh_pubkey: str


class SupportUser(SQLModel):
    """ Represents a support user. """
    username: str
    group: str
