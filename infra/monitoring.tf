resource "aws_sns_topic" "alerts" {
  name = "${local.name}-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  count = var.alert_email == "" ? 0 : 1

  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

locals {
  alarms = {
    dlq-not-empty = {
      description = "A message failed 3 times and was dead-lettered. Inspect the DLQ."
      namespace   = "AWS/SQS"
      metric      = "ApproximateNumberOfMessagesVisible"
      dimensions  = tomap({ QueueName = aws_sqs_queue.dlq.name })
      statistic   = "Maximum"
    }
    processor-errors = {
      description = "The processor Lambda is throwing errors."
      namespace   = "AWS/Lambda"
      metric      = "Errors"
      dimensions  = tomap({ FunctionName = aws_lambda_function.processor.function_name })
      statistic   = "Sum"
    }
    api-errors = {
      description = "The API Lambda is throwing errors."
      namespace   = "AWS/Lambda"
      metric      = "Errors"
      dimensions  = tomap({ FunctionName = aws_lambda_function.api.function_name })
      statistic   = "Sum"
    }
    api-5xx = {
      description = "API Gateway is returning 5xx responses."
      namespace   = "AWS/ApiGateway"
      metric      = "5xx"
      dimensions  = tomap({ ApiId = aws_apigatewayv2_api.http.id })
      statistic   = "Sum"
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "this" {
  for_each = local.alarms

  alarm_name          = "${local.name}-${each.key}"
  alarm_description   = each.value.description
  namespace           = each.value.namespace
  metric_name         = each.value.metric
  dimensions          = each.value.dimensions
  statistic           = each.value.statistic
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_dashboard" "pipeline" {
  dashboard_name = local.name
  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric", x = 0, y = 0, width = 12, height = 6
        properties = {
          title  = "Lambda invocations / errors"
          region = var.region
          stat   = "Sum"
          period = 60
          metrics = [
            ["AWS/Lambda", "Invocations", "FunctionName", aws_lambda_function.api.function_name],
            ["AWS/Lambda", "Errors", "FunctionName", aws_lambda_function.api.function_name],
            ["AWS/Lambda", "Invocations", "FunctionName", aws_lambda_function.processor.function_name],
            ["AWS/Lambda", "Errors", "FunctionName", aws_lambda_function.processor.function_name],
          ]
        }
      },
      {
        type = "metric", x = 12, y = 0, width = 12, height = 6
        properties = {
          title  = "Processor duration (ms)"
          region = var.region
          period = 60
          metrics = [
            ["AWS/Lambda", "Duration", "FunctionName", aws_lambda_function.processor.function_name, { stat = "p50" }],
            ["AWS/Lambda", "Duration", "FunctionName", aws_lambda_function.processor.function_name, { stat = "p95" }],
          ]
        }
      },
      {
        type = "metric", x = 0, y = 6, width = 12, height = 6
        properties = {
          title  = "Queue depth"
          region = var.region
          stat   = "Maximum"
          period = 60
          metrics = [
            ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", aws_sqs_queue.jobs.name],
            ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", aws_sqs_queue.dlq.name],
            ["AWS/SQS", "ApproximateAgeOfOldestMessage", "QueueName", aws_sqs_queue.jobs.name, { yAxis = "right" }],
          ]
        }
      },
      {
        type = "metric", x = 12, y = 6, width = 12, height = 6
        properties = {
          title  = "API requests / errors / latency"
          region = var.region
          period = 60
          metrics = [
            ["AWS/ApiGateway", "Count", "ApiId", aws_apigatewayv2_api.http.id, { stat = "Sum" }],
            ["AWS/ApiGateway", "4xx", "ApiId", aws_apigatewayv2_api.http.id, { stat = "Sum" }],
            ["AWS/ApiGateway", "5xx", "ApiId", aws_apigatewayv2_api.http.id, { stat = "Sum" }],
            ["AWS/ApiGateway", "Latency", "ApiId", aws_apigatewayv2_api.http.id, { stat = "p95", yAxis = "right" }],
          ]
        }
      },
    ]
  })
}
