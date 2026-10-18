output "api_url" {
  description = "Base URL of the HTTP API."
  value       = aws_apigatewayv2_stage.default.invoke_url
}

output "uploads_bucket" {
  value = aws_s3_bucket.uploads.bucket
}

output "processed_bucket" {
  value = aws_s3_bucket.processed.bucket
}

output "jobs_table" {
  value = aws_dynamodb_table.jobs.name
}

output "dashboard_url" {
  value = "https://${var.region}.console.aws.amazon.com/cloudwatch/home?region=${var.region}#dashboards:name=${aws_cloudwatch_dashboard.pipeline.dashboard_name}"
}
