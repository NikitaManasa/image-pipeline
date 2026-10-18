resource "aws_dynamodb_table" "jobs" {
  name         = "${local.name}-jobs"
  billing_mode = "PAY_PER_REQUEST" # no capacity planning, ~free at demo scale
  hash_key     = "job_id"

  attribute {
    name = "job_id"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at" # DynamoDB deletes expired jobs automatically, at no cost
    enabled        = true
  }

  point_in_time_recovery {
    enabled = true
  }
}
