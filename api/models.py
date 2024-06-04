import datetime

from os import getenv
from typing import Optional
from ipaddress import IPv4Address, IPv4Network

from pydantic import UUID4
from sqlalchemy.types import Text
from sqlmodel import Field, SQLModel, create_engine

from api.sql import get_sql_conn
from common.models import TunnelState
from common.util import expiry_datetime

# the default here is for the cloud environment.
SQL_URI = getenv("SQL_URI", "mysql+pymysql://")


class Tunnel(SQLModel, table=True):
    """ A support tunnel representation from the API's perspective. We
        take care not to store any sensitive key material here, or for
        what key material we do treat as "truth" here there is a secondary
        source of trust (for example, the wg preshared key being shared out-
        of-band.)
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    tunnel_id: UUID4
    state: TunnelState = Field(default=TunnelState.pending)
    # used for storing case #, customer details, etc
    description: Optional[str]
    created_at: datetime.datetime = Field(
        default_factory=datetime.datetime.now
    )
    expires: datetime.datetime = Field(
        default_factory=expiry_datetime
    )
    stopped_at: Optional[datetime.datetime]

    support_user: Optional[str]
    device_wg_public_key: str

    ts_instance_id: Optional[str]
    ts_wg_public_key: Optional[str]
    ts_public_ip: Optional[IPv4Address]
    ts_wg_port: Optional[int]

    network: IPv4Network

    # The below secret box is encrypted using the device pubkey +
    # the admin privkey. This gets us integrity and authenticity.
    # The fact that it gets us privacy is unintentional and just a
    # side effect of the pynacl library's message signing flow
    # disallowing arbitrary private key instantiation (ie, from wg),
    # instead necessitating a seed.
    #
    # This was chosen over symmetric encryption with the preshared key
    # simply because the preshared key actually gets transmitted places
    # and is something the untrusted tunnel-instantiator controls, instead
    # of the support operator.
    # ref: https://pynacl.readthedocs.io/en/latest/public/
    #    & https://pynacl.readthedocs.io/en/latest/signing/
    # See: https://github.com/tiangolo/sqlmodel/discussions/746
    support_secret_box: Optional[str] = Field(sa_type=Text)


if "sqlite" in SQL_URI:
    engine = create_engine(SQL_URI)
else:
    engine = create_engine(SQL_URI, creator=get_sql_conn, echo=True)

SQLModel.metadata.create_all(engine)
