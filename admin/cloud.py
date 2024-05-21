import logging

from os import getenv
from typing import Type, cast

from pydantic import UUID4
from jinja2 import Environment, FileSystemLoader, select_autoescape
from libcloud.compute.types import Provider
from libcloud.compute.providers import get_driver
from libcloud.compute.base import Node, NodeImage, NodeSize
from libcloud.compute.drivers.gce import GCENodeDriver

from common.constants import INSTANCE_NAME_PREFIX

SERVICE_ACCOUNT_USERNAME = getenv("SERVICE_ACCOUNT_USERNAME")
SERVICE_ACCOUNT_CREDENTIALS_JSON_FILE = getenv(
    "SERVICE_ACCOUNT_CREDENTIALS_JSON_FILE")
PROJECT_ID = getenv("PROJECT_ID")
DATACENTER = getenv("DATACENTER", "us-central1-b")
ENV = getenv("ENV", "prod")

assert PROJECT_ID

cls = get_driver(Provider.GCE)
GCE = cast(Type[GCENodeDriver], cls)
if SERVICE_ACCOUNT_CREDENTIALS_JSON_FILE and SERVICE_ACCOUNT_USERNAME:
    # This branch helps run local, non-cloud, or test instances.
    driver = GCE(
        SERVICE_ACCOUNT_USERNAME,
        SERVICE_ACCOUNT_CREDENTIALS_JSON_FILE,
        project=PROJECT_ID,
        datacenter=DATACENTER
    )
else:
    # This branch fetches credentials from the metadata service directly
    driver = GCE("", "", project=PROJECT_ID, datacenter=DATACENTER)

jinja2_env = Environment(loader=FileSystemLoader(
    "admin/templates"), autoescape=select_autoescape())


def get_instance_image() -> NodeImage:
    """ Returns a NodeImage representing the latest Debian 12 """
    return driver.ex_get_image_from_family('debian-12', ['debian-cloud'])


def get_instance_size() -> NodeSize:
    """ Returns a NodeSize representing the cheapest available instance """
    # At present this is e2-micro. Automagically determining this is time-consuming.
    return driver.ex_get_size('e2-micro')


def get_ts_instance(tunnel_id: UUID4) -> Node:
    """ Given a tunnel id, fetch a Node record for its tunnel server. """
    return driver.ex_get_node(f"{INSTANCE_NAME_PREFIX}-{tunnel_id}")


def list_ts_instances() -> list[Node]:
    """ Lists tunnel server instances. At present, it just uses the 
        INSTANCE_NAME_PREFIX to determine if it is a tunnel server.
    """
    return [n for n in driver.list_nodes() if n.name.startswith(INSTANCE_NAME_PREFIX)]


def create_ts_instance(tunnel_id: UUID4) -> Node:
    """ Handles creating a tunnel server. """
    # TODO: set up automatic termination.. maybe? or something more sophisticated
    # https://cloud.google.com/compute/docs/instances/limit-vm-runtime#gcloud_1
    logging.debug(f"creating ts instance for tunnel id {tunnel_id}")
    user_data_template = jinja2_env.get_template(
        "tunnel_server_user_data.sh.j2")
    user_data = user_data_template.render()

    ex_metadata = {
        "items": [
            {"key": "startup-script", "value": user_data}
        ]
    }

    i = driver.create_node(
        name=f"{INSTANCE_NAME_PREFIX}-{tunnel_id}",
        size=get_instance_size(),
        image=get_instance_image(),
        ex_metadata=ex_metadata,
        ex_network=f"support-tunnel-{ENV}",
        ex_subnetwork=f"ts-{ENV}",
        ex_tags=["support-tunnel"]
    )
    return i
