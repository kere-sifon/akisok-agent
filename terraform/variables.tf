variable "aws_region" {
  description = "AWS region used by the curation agent Bedrock client."
  type        = string
}

variable "bedrock_model_arn" {
  description = "ARN of the Bedrock model the agent is allowed to invoke. Do not hardcode in application code."
  type        = string
}

variable "curation_role_name" {
  description = "IAM role name for a future scheduled runner of the curation pipeline."
  type        = string
  default     = "akisok-curation-agent"
}

variable "atlas_project_id" {
  description = "MongoDB Atlas project ID. Used only if mongodbatlas_search_index in mongo.tf is enabled."
  type        = string
  default     = ""
}

variable "atlas_cluster_name" {
  description = "MongoDB Atlas cluster name. Used only if mongodbatlas_search_index in mongo.tf is enabled."
  type        = string
  default     = ""
}

variable "mongodb_db_name" {
  description = "Atlas database that holds review_queue and dedup_embeddings."
  type        = string
  default     = "akisok"
}
