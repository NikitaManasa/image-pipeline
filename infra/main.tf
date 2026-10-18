data "aws_caller_identity" "current" {}

locals {
  name       = var.project
  account_id = data.aws_caller_identity.current.account_id

  lambda_env = {
    JOBS_TABLE       = aws_dynamodb_table.jobs.name
    UPLOADS_BUCKET   = aws_s3_bucket.uploads.bucket
    PROCESSED_BUCKET = aws_s3_bucket.processed.bucket
    MAX_UPLOAD_BYTES = tostring(var.max_upload_mb * 1024 * 1024)
  }
}
