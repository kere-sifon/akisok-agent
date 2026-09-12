terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

data "aws_iam_policy_document" "curation_assume" {
  statement {
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }

    actions = ["sts:AssumeRole"]
  }
}

resource "aws_iam_role" "curation_agent" {
  name               = var.curation_role_name
  assume_role_policy = data.aws_iam_policy_document.curation_assume.json
}

data "aws_iam_policy_document" "bedrock_invoke" {
  statement {
    sid    = "InvokeConfiguredBedrockModel"
    effect = "Allow"
    actions = [
      "bedrock:InvokeModel",
      "bedrock:InvokeModelWithResponseStream",
      "bedrock:Converse",
      "bedrock:ConverseStream",
    ]
    resources = [var.bedrock_model_arn]
  }
}

resource "aws_iam_role_policy" "bedrock_invoke" {
  name   = "${var.curation_role_name}-bedrock"
  role   = aws_iam_role.curation_agent.id
  policy = data.aws_iam_policy_document.bedrock_invoke.json
}
