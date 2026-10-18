# Least privilege: one role per function, each allowed only the exact actions and resources it uses.

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "api" {
  name               = "${local.name}-api"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role" "processor" {
  name               = "${local.name}-processor"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "api" {
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.api.arn}:*"]
  }
  statement {
    sid       = "Jobs"
    actions   = ["dynamodb:PutItem", "dynamodb:GetItem"]
    resources = [aws_dynamodb_table.jobs.arn]
  }
  statement {
    sid       = "SignUploadUrls" # presigned POSTs are signed with this role's credentials
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.uploads.arn}/uploads/*"]
  }
  statement {
    sid       = "SignDownloadUrls"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.processed.arn}/processed/*"]
  }
}

data "aws_iam_policy_document" "processor" {
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.processor.arn}:*"]
  }
  statement {
    sid       = "ConsumeQueue"
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
    resources = [aws_sqs_queue.jobs.arn]
  }
  statement {
    sid       = "ReadUploads"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.uploads.arn}/uploads/*"]
  }
  statement {
    sid       = "WriteRenditions"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.processed.arn}/processed/*"]
  }
  statement {
    sid       = "UpdateJobs"
    actions   = ["dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.jobs.arn]
  }
}

resource "aws_iam_role_policy" "api" {
  name   = "least-privilege"
  role   = aws_iam_role.api.id
  policy = data.aws_iam_policy_document.api.json
}

resource "aws_iam_role_policy" "processor" {
  name   = "least-privilege"
  role   = aws_iam_role.processor.id
  policy = data.aws_iam_policy_document.processor.json
}

resource "aws_iam_role_policy_attachment" "xray" {
  for_each = {
    api       = aws_iam_role.api.name
    processor = aws_iam_role.processor.name
  }

  role       = each.value
  policy_arn = "arn:aws:iam::aws:policy/AWSXRayDaemonWriteAccess"
}
