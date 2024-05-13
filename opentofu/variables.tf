variable "domain" {
  description = "The domain used to instantiate various services. This gets var.env prepended"
  type        = string
}

variable "env" {
  description = "The environment this is deployed in; test, dev, prod, etc."
  type        = string
  default     = "dev"
}

variable "region" {
  description = "The region to deploy services into. Most things default to the provider region, but some resources need it hardcoded"
  type        = string
  default     = "us-central1"
}

variable "repo_name" {
  description = "The repo name to use for setting up OIDC auth between Github <-> Google Cloud for deploys. ex: micro-nova/support_tunnel"
  type        = string
  default     = "micro-nova/support_tunnel"
}

variable "trusted_ip_ranges" {
  description = "IP ranges which we should permit SSH traffic from"
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "trusted_domain" {
  description = "The trusted Google cloud domain. Right now, just used to permit assigning a ServiceAccount to the tunnel instance"
  type        = string
}
