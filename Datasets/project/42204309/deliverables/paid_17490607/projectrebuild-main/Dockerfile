# Multi-stage Dockerfile for Project Rebuild Smart Contracts
FROM node:20 AS base

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    git \
    build-essential \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Foundry
RUN curl -L https://foundry.paradigm.xyz | bash && \
    export PATH="/root/.foundry/bin:${PATH}" && \
    foundryup

ENV PATH="/root/.foundry/bin:${PATH}"

# Verify Foundry installation
RUN forge --version && cast --version && anvil --version

# Set working directory
WORKDIR /app

# Copy package files
COPY package.json package-lock.json* ./

# Install Node.js dependencies (if any)
RUN npm install || true

# Copy project files
COPY . .

# Install Foundry dependencies
RUN forge install OpenZeppelin/openzeppelin-contracts || true
RUN forge install smartcontractkit/chainlink || true

# Build stage
FROM base AS builder

# Compile contracts
RUN forge build || echo "Build may fail if dependencies missing, will install in runtime"

# Development stage
FROM base AS development

# Default command (can be overridden)
CMD ["anvil", "--host", "0.0.0.0", "--port", "8545"]

# Production stage
FROM base AS production

# Set environment variables
ENV NODE_ENV=production

# Default command for production
CMD ["forge", "test"]

