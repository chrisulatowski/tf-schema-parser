#!/bin/bash

# Get the directory of the script
SCRIPT_DIR=$(dirname "$(realpath "$0")")

SCHEMA_DIR="$SCRIPT_DIR"
SCHEMA_FILE="$SCHEMA_DIR/azurerm_schema.json"
PROVIDER_PATH="$SCHEMA_DIR/.terraform/providers/registry.terraform.io/hashicorp/azurerm"

echo "Initializing Terraform if not already done..."
terraform init

if [ $? -ne 0 ]; then
  echo "Failed to initialize Terraform."
  exit 1
fi

echo "Downloading azurerm provider schema to $SCHEMA_FILE..."
terraform providers schema -json > "$SCHEMA_FILE"

if [ $? -eq 0 ]; then
  echo "Schema downloaded successfully."
  if [ -d "$PROVIDER_PATH" ]; then
    echo "Removing provider binaries to free up space..."
    rm -rf "$PROVIDER_PATH"
    echo "Provider binaries removed."
  else
    echo "Provider binaries folder not found, skipping deletion."
  fi
else
  echo "Failed to download schema."
  exit 1
fi
