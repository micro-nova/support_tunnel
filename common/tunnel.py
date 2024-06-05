import io
import random
import socket
import logging

from typing import List, Union
from ipaddress import IPv4Network, IPv4Interface

from pyroute2 import IPRoute
from fabric import Connection as FabricConnection

from common.models import WireguardTunnel
from device.local_context import LocalContext


def get_current_routes() -> List[IPv4Network]:
    """ Return the current routes on a device. """
    ipr = IPRoute()
    current_routes = ipr.get_routes(family=socket.AF_INET)
    # pyroute2's representation of routes is closer to the OS than
    # what the ipaddress library wants as input; the below converts
    # all routes to something like ['10.20.30.0/24', '127.0.0.1/32', ...]
    current_routes_strings = [
        f"{dict(i['attrs'])['RTA_DST']}/{i['dst_len']}"
        for i in current_routes
        if dict(i['attrs']).get('RTA_DST')
    ]
    return [IPv4Network(n) for n in current_routes_strings]


def allocate_address_space() -> IPv4Network:
    """ Tests that the given private address space is not used
        on any local interfaces. If it is, try a new network.
        Return an unused address space.
    """
    # There are more private ranges than this, but let's not get too fancy.
    # We pre-compute the 10./8 subnets so the later `.subnets(new_prefix)` call
    # is not too heavy on small computers
    candidate_ranges = [
        IPv4Network('172.16.0.0/12'),
        IPv4Network('192.168.0.0/16')
    ]
    for r in IPv4Network('10.0.0.0/8').subnets(prefixlen_diff=4):
        candidate_ranges.append(r)

    current_routes = get_current_routes()
    counter = 0
    while counter < 1000:  # try 1000 networks
        # Choose a private range to split up into smaller prefixes
        supernet = random.choice(candidate_ranges)
        logging.debug(f"allocate_address_space supernet: {supernet}")
        # we use a /28 netmask because generating this list for
        # larger networks on small computers is nontrivial
        net_choices = [i for i in supernet.subnets(new_prefix=28)]
        net = random.choice(net_choices)
        logging.debug(f"allocate_address_space network to test: {net}")

        # Test if the selected network overlaps with existing routes...
        if any([net.overlaps(i) for i in current_routes]):
            # If it does, restart the loop and try a new network.
            counter += 1
            continue
        return net

    # no network was found! raise
    raise Exception("No usable networks found.")


def write_wireguard_config(c: Union[LocalContext, FabricConnection], t: WireguardTunnel):
    """ Writes a wireguard config to disk. """
    logging.debug(
        f"writing wireguard config for interface {t.interface} to disk...")
    wg_config_filelike = io.StringIO(
        t.to_WireguardConfig().to_wgconfig(wgquick_format=True))
    c.put(wg_config_filelike, f"/tmp/{t.interface}.conf")
    c.run("sudo mkdir -p /etc/wireguard")
    c.run("sudo chown root:root /etc/wireguard")
    c.run("sudo chmod 0600 /etc/wireguard")
    c.run(f"sudo mv /tmp/{t.interface}.conf /etc/wireguard/{t.interface}.conf")
    c.run(f"sudo chown root:root /etc/wireguard/{t.interface}.conf")
    c.run(f"sudo chmod 0500 /etc/wireguard/{t.interface}.conf")


def start_wireguard_tunnel(c: Union[LocalContext, FabricConnection], t: WireguardTunnel):
    """ Starts a wireguard tunnel using an invoke context. The
        invoke context allows this to be run on local or remote.
        This assumes the host in question has a local wireguard config already.
    """
    logging.debug(f"starting wg tunnel on interface {t.interface}")
    try:
        c.run(f"sudo systemctl enable wg-quick@{t.interface}")
        c.run(f"sudo systemctl start wg-quick@{t.interface}")
    except Exception as e:
        # Clean up our resources; don't leave things hanging around.
        c.run(f"sudo systemctl stop wg-quick@{t.interface}", warn=True)
        c.run(f"sudo systemctl disable wg-quick@{t.interface}", warn=True)
        raise e
    return t.interface


def host_in_network(n: int, net: IPv4Network) -> IPv4Interface:
    """ Returns the nth host in the network.
    """
    # TODO: the below shouldn't be necessary 🥴
    if isinstance(net, str):
        net = IPv4Network(net)
    host = [i for i in net.hosts()][n]
    return IPv4Interface(f"{str(host)}/{net.prefixlen}")


def device_ip(net: IPv4Network) -> IPv4Interface:
    """ Returns the device IP. We're cheap with this for now; just choose
        the first host address.
    """
    return host_in_network(0, net)


def server_ip(net: IPv4Network) -> IPv4Interface:
    """ Returns the server IP. We're cheap with this for now; just choose
        the second host address.
    """
    return host_in_network(1, net)
