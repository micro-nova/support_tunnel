# `support-tunnel`

This repo contains a secure implementation of a support tunnel. Its implementation emphasizes user consent, privacy, and security for all parties. At a high level, it instantiates a quantum-resistant Wireguard tunnel between an ephemerally launched cloud server and a remote device, using an API as a bookkeeping intermediary and some additional key material exchanged out of band.

It uses a couple of technologies:
* [Fabric](https://www.fabfile.org/) - used to control the remote tunnel server
* [Invoke](https://www.pyinvoke.org/) - used to run commands on localhost
* [SQLModel](https://sqlmodel.tiangolo.com/) - a nice ORM from [tiangolo](https://github.com/tiangolo), built on [Pydantic](https://docs.pydantic.dev/latest/)
* [FastAPI](https://fastapi.tiangolo.com/) - a nice web framework from [tiangolo](https://github.com/tiangolo)

## How to use this

Some quick terms:
* `device` is the remote thing you'd like access to
* `admin` is the support user's context, both on their local laptop and the launched tunnel server.
* `api` is the API. It's main purpose is to do bookkeeping and exchange bootstrapping data.

### Setup
First, if this is a greenfield deployment, launch the cloud network and an instance of the API. See more detailed instructions in the `opentofu/README.md` documentation on how to accomplish this. If you're a Micro-Nova employee, you can skip this step.

Then, on both the device you'd like a tunnel on and on your admin computer:
```
apt install libsystemd-dev wireguard wireguard-tools
git clone https://github.com/micro-nova/support_tunnel
pushd support_tunnel
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### `device`

Create a `support` group. Certain functions require root, like opening a wireguard device. Others don't. We use a `support` group for the backing SQLite database to share this between both contexts. For any non-root user calling these services, add them to this group.

```
groupadd support
```

Request a tunnel on your `device`. If you are a Micro-Nova employee, this is more or less what the updater does when you press the "Request support tunnel" button.

```
inv --list                          # see what commands are available
# request a tunnel and wait until approval
inv request-and-connect-tunnel      # there are also separate request and connect commands
```
This will print both a tunnel ID and a preshared key. These should be transmitted to the `admin` out of band, likely through a typical support channel.

### `admin`

On your `admin`, you probably need to log in to a cloud provider so you can start and configure instances. For Micro-Nova, this is Google Cloud Platform. Install the [`gcloud` utility](https://cloud.google.com/sdk/docs/install-sdk) and run these steps:
```
gcloud init
gcloud auth application-default login
gcloud compute os-login ssh-keys add --ttl=120d --key-file=$(realpath ~/.ssh/id_ed25519.pub)
```
To note, your public key may live someplace else or be in a different format; please modify the command to suit. Also to note - authenticating to tunnel servers will fail unless you have 2FA configured on your Google account. Please [configure 2FA](https://support.google.com/accounts/answer/185839).


```
fab --list # see what commands are available
# create the tunnel server, using the preshared key and tunnel id from the device
fab create
fab show $TUNNEL_ID
fab connect $TUNNEL_ID
fab command $TUNNEL_ID 'cat /etc/hostname'
```

The above takes a while. When it completes though, you should be logged in as root on the remote device!

## Code structure
* `api/` - all the API server code
* `device/` - all the client (ie AmpliPi) code
* `admin/` - all the launched tunnel server code
* `common/` - code that is shared, notably data models
* `opentofu/` - code to deploy the API server, LB, network, etc in Google Cloud Platform using OpenTofu
