terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.80"
    }
  }

  # Remote state in S3 with native locking. Bucket name is passed at init time:
  #   terraform init -backend-config="bucket=<state bucket>" -backend-config="region=<region>"
  backend "s3" {
    key          = "image-pipeline/terraform.tfstate"
    use_lockfile = true
    encrypt      = true
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project   = var.project
      ManagedBy = "terraform"
      Repo      = "github.com/NikitaManasa/image-pipeline"
    }
  }
}
