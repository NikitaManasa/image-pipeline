variable "region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "us-east-1"
}

variable "project" {
  description = "Prefix for every resource name."
  type        = string
  default     = "image-pipeline"
}

variable "alert_email" {
  description = "Email that receives CloudWatch alarm notifications (confirm the subscription email). Empty = no email."
  type        = string
  default     = ""
}

variable "max_upload_mb" {
  description = "Largest image a client may upload."
  type        = number
  default     = 10
}

variable "processor_timeout_seconds" {
  description = "Processor Lambda timeout; the SQS visibility timeout is derived from it."
  type        = number
  default     = 60
}

variable "api_zip" {
  description = "Path to the API Lambda package built by scripts/build.py."
  type        = string
  default     = "../build/api.zip"
}

variable "processor_zip" {
  description = "Path to the processor Lambda package built by scripts/build.py."
  type        = string
  default     = "../build/processor.zip"
}
