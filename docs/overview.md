# Overview

This document presents a high level overview of the flow of information and steps taken to establish a support tunnel, in technical detail. It is intended to show at a high level that this implementation is securely designed.

## Requesting a tunnel

When a request is initiated from a `device`, some initial values are generated - an Ed25519 public+private keypair and a small private subnet that isn't already present in the device's routing table. It saves these values into a local SQLite DB.

Then a `device` requests a tunnel from the `api`, running in the cloud. This request contains the public key and the private network subnet to store in the `api`'s database, and will return a JWT that contains a `tunnel_id` and an expiry time. From this point on, the `device` can only interact with the API by returning this JWT as a bearer token, identifying it as this particular tunnel.

Finally, the `device` generates a preshared key and stores it into the local SQLiteDB. It returns the `tunnel_id` and `preshared_key` for the end user to send out of band in a support request. From now until the expiry time, or until the tunnel is started/aborted, the `device` should check to see if any requested tunnels have been approved, and if so set them up. This is accomplished in our reference implementation with a cronjob.

## Approving a tunnel

When a support request is received with these details, the tunnel is then approved or denied. When a tunnel is approved, the support engineer provides the `tunnel_id` and the `preshared_key` provided by the user to a local CLI application. This local application will start a server in the cloud and configure it using [Fabric](https://www.fabfile.org/).

The cloud server will generate its own Ed25519 public+private keypair, and store the public IP and public key in the API's database. The cloud server is configured by the local CLI app to start a WireGuard tunnel, using the local public+private keypair, the preshared key, and the `device`'s public key. A `support` user is created and an SSH key is generated to permit keyed access to the remote device. The public SSH key is stored in a NaCl Box, encrypted with the `device'`s public key and the tunnel server's private key, ensuring this could only be set from the trusted cloud server. Finally, it updates the API to say it is configured and waiting for an incoming connection from a remote `device`.

SSH authentication to these launched cloud servers is provided using [GCP's OS Login](https://cloud.google.com/compute/docs/oslogin) and two factor authentication. Support engineer authentication to the API is provided using a bearer token stored in [GCP Secret Manager](https://cloud.google.com/security/products/secret-manager). No private nor preshared key is ever stored with the API.

## Tunnel instantiation

The device checks back in and finds that the tunnel has been approved and there is a cloud server waiting for it. It starts its own WireGuard tunnel using the public IP and public key of the cloud server (fetched from the API). It also generates an ephemeral support user with a random prefix, unwraps the SSH `authorized_keys` entry from the NaCL box and creates it, and gives this user sudo permissions. The WireGuard tunnel send a persistent keepalive pretty frequently, to poke an outbound hole in any firewalls or NATs. At this point, a WireGuard tunnel is established.

## Support usage

The support user provides the tunnel_id they wish to connect to. Fabric will use the created tunnel server as a bastion host/jump box and drop them to a root shell on the remote box. To get to this point, multiple layers of authentication must have occurred:
* the preshared key must have been transmitted out of band from the end user
* the support user must have access to the bearer token stored in GCP to interact with the API
* the support user must have a user configured in OS Login and 2FA on their Google account to log into any cloud server

## Wrapping up tunnel usage

The original JWT that identified the device's tunnel instance to the API expires after some time. This time is recorded in the database, as well as any users or WireGuard tunnel instances established. When tunnels are explicitly stopped or they expire past this time, regular garbage collection of resources will stop tunnels and remove users. In our reference implementation, this is accomplished by a cronjob.
