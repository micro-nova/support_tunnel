# `opentofu/`

This repo is a set of [OpenTofu](https://opentofu.org) instructions for hosting the cloud infrastructure for this support tunnel service in Google Cloud Platform.

## how to

First, [install OpenTofu](https://opentofu.org/docs/intro/install/).

Then [install `gcloud`](https://cloud.google.com/sdk/docs/install-sdk) and authenticate to Google Cloud Platform:

```
gcloud auth application-default login
```

Then [install the GitHub CLI client, `gh`](https://cli.github.com/), and authenticate:

```
gh auth login
```

Define an `.env` for use with this project; fill out these details from your Cloud Console:

```
export GOOGLE_CLOUD_PROJECT=babbling-brook-6543
export GOOGLE_REGION=us-central1
export TF_VAR_env="dev"
```

Also define a `backend.tfvars` file for some variables used for storing state:

```
bucket = "MY_FANCY_BUCKET_NAME_HERE"
```

If you want help configuring these values, consult @rtertiaer.

Then,


```
source .env
tofu init -backend-config=backend.tfvars
# make some changes
tofu plan
# does the plan look okay? does it terminate or rotate any resources unintentionally? if it all looks good...
tofu apply
```

## notes

Take care creating, deleting and recreating these resources. There are a couple things here:
* The first deploy of fresh infrastructure will fail due to no image being present in the container repository, and thus the Cloud Run api service not starting. Let it create as much infra as it can, then push an image to the repo (probably by pushing a commit.) Then create a new revision of the Cloud Run service, and run `tofu improt google_cloud_run_v2_service.api $REGION/api-$ENV`, then finally `tofu apply` to complete the rest of the dependent infrastructure - namely load balancers and DNS records.
* IAM Workload Identity Pools and related resources do not actually delete. They enter a soft-deleted state and are permenantly deleted after 30 days. `gcloud` has an `undelete` option for these resources. If you want to briefly disable them, these resources tend to have a `disabled` option.
* Sometimes the IP address allocation for VPC peering to the SQL DB hangs around even after telling tofu this resource has been deleted. Thus, deleting the VPC or associated networks will fail. Wait a while and try again from the web console - it seems to do a better job cleaning up various resources that tofu isn't aware of.
