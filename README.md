# `support-tunnel`

This repo contains a relatively secure implementation of a support tunnel. Its implementation emphasizes user consent, privacy, and security for all parties. At a high level, it instantiates a quantum-resistant Wireguard tunnel between an ephemerally launched cloud server and a remote device, using an API as a bookkeeping intermediary and some additional key material exchanged out of band.

It uses a couple of technologies:
* [Fabric](https://www.fabfile.org/) - used to control the remote tunnel server
* [Invoke](https://www.pyinvoke.org/) - used to run commands on localhost
* [SQLModel](https://sqlmodel.tiangolo.com/) - a nice ORM from [tiangolo](https://github.com/tiangolo), built on [Pydantic](https://docs.pydantic.dev/latest/)
* [FastAPI](https://fastapi.tiangolo.com/) - a nice web framework from [tiangolo](https://github.com/tiangolo)
* [libcloud](https://libcloud.readthedocs.io/en/stable/) - an Apache cloud library to help prevent vendor lock-in.

## quickstart

Some quick terms:
* `device` is the remote thing you'd like access to
* `admin` is the support user's context, both on their local laptop and the launched tunnel server.
* `api` is the API. It's main purpose is to do bookkeeping and exchange bootstrapping data.

First, if this is a greenfield deployment, launch the cloud network and an instance of the API. See more detailed instructions in the `opentofu/README.md` documentation on how to accomplish this. If you're a Micro-Nova employee, you can skip this step.

Then, on both the device you'd like a tunnel on and on your admin computer:
```
git clone https://github.com/micro-nova/support_tunnel
pushd support_tunnel
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

On your `device`:
```
inv --list # see what commands are available
# request a tunnel and wait until approval
inv request-and-connect-tunnel
```
This will print both a tunnel ID and a preshared key. These should be transmitted to the `admin` out of band, likely through a typical support channel.

On your `admin`, you need to log in to the cloud provider. At present, this is Google Cloud Platform. Install the [`gcloud` utility](https://cloud.google.com/sdk/docs/install-sdk) and authenticate using `gcloud auth`, then:

```
fab --list # see what commands are available
# create the tunnel server, using the preshared key and tunnel id from the device
fab create-tunnel-server -p $PRESHARED_KEY -t $TUNNEL_ID
fab get $TUNNEL_ID
```

The above takes a while. When it completes though, you should be able to log in to your newly created server in GCP, `sudo su support`, then `ssh $SUPPORT_USERNAME@$DEVICE_IP`. (This side of the process could be improved.)

## Code structure
* `api/` - all the API server code
* `device/` - all the client (ie AmpliPi) code
* `admin/` - all the launched tunnel server code
* `common/` - code that is shared, notably data models
* `opentofu/` - code to deploy the API server, LB, network, etc in Google Cloud Platform using OpenTofu


