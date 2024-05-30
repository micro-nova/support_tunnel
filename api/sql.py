import pymysql

from os import getenv
from google.cloud import secretmanager
from google.cloud.sql.connector import Connector, IPTypes

from common.util import project_id

ENV = getenv("ENV")
PROJECT_ID = project_id()
assert ENV
assert PROJECT_ID

SQL_USER = getenv("SQL_USER", f"api-{ENV}")
SQL_INSTANCE = getenv("SQL_INSTANCE", f"{PROJECT_ID}:us-central1:api-{ENV}")


def get_sql_conn() -> pymysql.connections.Connection:
    connector = Connector(IPTypes.PRIVATE)
    conn: pymysql.connections.Connection = connector.connect(
        SQL_INSTANCE,
        "pymysql",
        user=SQL_USER,
        password=get_sql_password(),
        db="support-tunnel"
    )
    return conn


def get_sql_password() -> str:
    p = getenv("SQL_PASSWORD")
    if not p:
        c = secretmanager.SecretManagerServiceClient()
        response = c.access_secret_version(
            request={"name": f"projects/{PROJECT_ID}/secrets/sql-password-{ENV}/versions/latest"})
        p = response.payload.data.decode("UTF-8")
    return p
