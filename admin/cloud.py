import logging

from os import getenv
from ipaddress import IPv4Address

from pydantic import UUID4
from google.cloud import compute_v1
from jinja2 import Environment, FileSystemLoader, select_autoescape

from common.util import project_id
from common.constants import INSTANCE_NAME_PREFIX

ZONE = getenv("ZONE", "us-central1-b")
REGION = ZONE[0:-2]
ENV = getenv("ENV", "prod")
PROJECT_ID = project_id()

jinja2_env = Environment(loader=FileSystemLoader(
    "admin/templates"), autoescape=select_autoescape())

def get_instance_image() -> str:
    """ Returns a str representing the latest Debian 12, in the format wanted by AttachedDiskInitializeParams """
    image_client = compute_v1.ImagesClient()
    i = image_client.get_from_family(project='debian-cloud', family='debian-12')
    return f"projects/debian-cloud/global/images/{i.name}"

def get_instance_size() -> str:
    """ Returns a size representing the cheapest available instance """
    # At present this is e2-micro. Automagically determining this is time-consuming.
    return 'e2-micro'

def get_ts_instance(tunnel_id: UUID4) -> compute_v1.Instance:
    """ Given a tunnel id, fetch a Node record for its tunnel server. """
    instance_client = compute_v1.InstancesClient()
    return instance_client.get(project=PROJECT_ID, zone=ZONE, instance=f"{INSTANCE_NAME_PREFIX}-{tunnel_id}")

def list_ts_instances() -> list[compute_v1.Instance]:
    """ Lists tunnel server instances. At present, it just uses the 
        INSTANCE_NAME_PREFIX to determine if it is a tunnel server.
    """
    instance_client = compute_v1.InstancesClient()
    return [n for n in instance_client.list(project=PROJECT_ID, zone=ZONE) if n.name.startswith(INSTANCE_NAME_PREFIX)]

def _create_ts_boot_disk() -> compute_v1.AttachedDisk:
    """ create a boot disk description for use with a tunnel server """
    disk = compute_v1.AttachedDisk()
    init_params = compute_v1.AttachedDiskInitializeParams()
    init_params.source_image = get_instance_image()
    init_params.disk_size_gb = 10
    init_params.disk_type = f"zones/{ZONE}/diskTypes/pd-standard"
    disk.initialize_params = init_params
    disk.auto_delete = True
    disk.boot = True
    return disk

def _create_ts_network_interfaces() -> list[compute_v1.NetworkInterface]:
    """ create a list of network interface descriptions """
    # create network interface & external access configs
    netiface = compute_v1.NetworkInterface()
    netiface.network = f"global/networks/support-tunnel-{ENV}"
    netiface.subnetwork = f"regions/{REGION}/subnetworks/ts-{ENV}"
    access = compute_v1.AccessConfig()
    access.type_ = compute_v1.AccessConfig.Type.ONE_TO_ONE_NAT.name
    access.name = "External NAT"
    access.network_tier = access.NetworkTier.PREMIUM.name
    netiface.access_configs = [access]
    return [netiface]

def _ts_instance_metadata():
    """ generate a GCP metadata blob for a tunnel server. Includes a Jinja2 rendered
        startup script.
    """
    user_data_template = jinja2_env.get_template(
        "tunnel_server_user_data.sh.j2")
    user_data = user_data_template.render()
    return {
        "items": [
            {"key": "startup-script", "value": user_data}
        ]
    }

def create_ts_instance(tunnel_id: UUID4) -> compute_v1.Instance:
    """ Handles creating a tunnel server. """
    # TODO: set up automatic termination.. maybe? or something more sophisticated
    # https://cloud.google.com/compute/docs/instances/limit-vm-runtime#gcloud_1

    instance_client = compute_v1.InstancesClient()

    logging.debug(f"creating ts instance for tunnel id {tunnel_id}")

    # create instance object
    i = compute_v1.Instance()
    i.network_interfaces = _create_ts_network_interfaces()
    i.name = f"{INSTANCE_NAME_PREFIX}-{tunnel_id}"
    i.disks = [_create_ts_boot_disk()]
    i.machine_type = f"zones/{ZONE}/machineTypes/{get_instance_size()}"
    i.metadata = _ts_instance_metadata()

    # create the request
    req = compute_v1.InsertInstanceRequest()
    req.zone = ZONE
    req.project = PROJECT_ID
    req.instance_resource = i

    # run it
    try:
        operation = instance_client.insert(request=req)
        operation.result(timeout=120)
        if operation.error_code:
            raise operation.exception() or RuntimeError(operation.error_message)
    except Exception as e:
        logging.exception("failed to create a tunnel server instance!")
        raise e

    return get_ts_instance(tunnel_id)

def get_ts_instance_public_ip(tunnel_id: UUID4) -> IPv4Address:
    """ Using only the GCP API and our instance naming convention,
        determine a given tunnel_id's running server public IP.
    """
    i = get_ts_instance(tunnel_id)
    return IPv4Address(i.network_interfaces[0].access_configs[0].nat_i_p)
