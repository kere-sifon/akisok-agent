output "curation_agent_role_arn" {
  description = "IAM role the pipeline runner should assume for Bedrock access."
  value       = aws_iam_role.curation_agent.arn
}

output "bedrock_model_arn" {
  description = "Configured Bedrock model ARN (pass the matching ID to BEDROCK_MODEL_ID)."
  value       = var.bedrock_model_arn
}
