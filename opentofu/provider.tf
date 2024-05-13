terraform {
  required_providers {
    github = {
      source  = "integrations/github"
      version = "~> 6.0"
    }
  }
}

provider "google" {}
provider "github" {
  owner = "micro-nova"
}
