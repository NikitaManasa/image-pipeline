resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/lambda/${local.name}-api"
  retention_in_days = 14
}

resource "aws_cloudwatch_log_group" "processor" {
  name              = "/aws/lambda/${local.name}-processor"
  retention_in_days = 14
}

resource "aws_lambda_function" "api" {
  function_name    = "${local.name}-api"
  role             = aws_iam_role.api.arn
  runtime          = "python3.12"
  architectures    = ["x86_64"]
  handler          = "pipeline.api.handler"
  filename         = var.api_zip
  source_code_hash = filebase64sha256(var.api_zip)
  memory_size      = 256
  timeout          = 10

  environment {
    variables = local.lambda_env
  }

  tracing_config {
    mode = "Active" # X-Ray traces each request through API Gateway -> Lambda -> DynamoDB/S3
  }

  depends_on = [aws_cloudwatch_log_group.api, aws_iam_role_policy.api]
}

resource "aws_lambda_function" "processor" {
  function_name    = "${local.name}-processor"
  role             = aws_iam_role.processor.arn
  runtime          = "python3.12"
  architectures    = ["x86_64"] # must match the Pillow wheel bundled by scripts/build.py
  handler          = "pipeline.processor.handler"
  filename         = var.processor_zip
  source_code_hash = filebase64sha256(var.processor_zip)
  memory_size      = 1024 # image decoding is CPU-bound; Lambda CPU scales with memory
  timeout          = var.processor_timeout_seconds

  environment {
    variables = local.lambda_env
  }

  tracing_config {
    mode = "Active"
  }

  depends_on = [aws_cloudwatch_log_group.processor, aws_iam_role_policy.processor]
}

resource "aws_lambda_event_source_mapping" "jobs" {
  event_source_arn                   = aws_sqs_queue.jobs.arn
  function_name                      = aws_lambda_function.processor.arn
  batch_size                         = 5
  maximum_batching_window_in_seconds = 1
  function_response_types            = ["ReportBatchItemFailures"] # retry only the failed messages

  scaling_config {
    maximum_concurrency = 2 # caps cost and protects downstream services during upload bursts
  }
}
