#!/bin/bash
# Setup script to install Foundry dependencies

set -e

echo "Installing Foundry dependencies..."

# Initialize git if not already initialized
if [ ! -d .git ]; then
    git init
    git config user.email "dev@projectrebuild.com"
    git config user.name "Project Rebuild Dev"
fi

# Install dependencies if lib directory is empty or missing
if [ ! -d "lib/openzeppelin-contracts" ]; then
    echo "Installing OpenZeppelin contracts..."
    forge install OpenZeppelin/openzeppelin-contracts
fi

if [ ! -d "lib/chainlink" ]; then
    echo "Installing Chainlink contracts..."
    forge install smartcontractkit/chainlink
fi

echo "Dependencies installed successfully!"

