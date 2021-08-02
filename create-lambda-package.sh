#!/bin/bash

cd vault/package
zip -r ../custom_resource_vault.zip .
cd ..
zip -g custom_resource_vault.zip index.py

aws s3 cp custom_resource_vault.zip s3://umgc-cca-670/custom_resource_vault.zip