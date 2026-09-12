# Atlas Vector Search for Phase 2 duplicate detection.
#
# TODO (manual, once per cluster): create a Vector Search index on
# collection `dedup_embeddings` named `dedup_embeddings_index`.
#
# Atlas UI steps:
# 1. Database → Search / Vector Search → Create Search Index
# 2. Collection: <MONGODB_DB_NAME>.dedup_embeddings
# 3. Index name: dedup_embeddings_index
# 4. JSON:
#    {
#      "fields": [
#        {
#          "type": "vector",
#          "path": "embedding",
#          "numDimensions": 1024,
#          "similarity": "cosine"
#        },
#        { "type": "filter", "path": "created_at" }
#      ]
#    }
# Titan Text Embeddings V2 default output is 1024 dimensions; change
# numDimensions if you override the model output size.
#
# mongodbatlas provider sketch (uncomment after adding the provider
# and project/cluster variables — not applied in this pass):
#
# resource "mongodbatlas_search_index" "dedup_embeddings" {
#   project_id    = var.atlas_project_id
#   cluster_name  = var.atlas_cluster_name
#   name          = "dedup_embeddings_index"
#   database      = var.mongodb_db_name
#   collection_name = "dedup_embeddings"
#   type          = "vectorSearch"
#   fields        = jsonencode([
#     {
#       type           = "vector"
#       path           = "embedding"
#       numDimensions  = 1024
#       similarity     = "cosine"
#     },
#     {
#       type = "filter"
#       path = "created_at"
#     }
#   ])
# }
