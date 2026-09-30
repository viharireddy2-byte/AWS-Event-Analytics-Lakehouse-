# Local state is the sandbox default. For shared deployments, configure an S3
# backend with an encrypted, versioned bucket and a DynamoDB LockID table.
# Credentials come from the standard AWS credential chain, never this file.
# terraform {
#   backend "s3" {}
#
# }
# See docs/deployment.md for migration instructions.
