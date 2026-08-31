# Docker Guide - Project Rebuild

Complete guide for building, running, testing, and deploying the Project Rebuild smart contracts using Docker.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Docker Services](#docker-services)
- [Building Images](#building-images)
- [Running Services](#running-services)
- [Testing](#testing)
- [Compilation](#compilation)
- [Development Workflow](#development-workflow)
- [Deployment](#deployment)
- [Troubleshooting](#troubleshooting)

## Prerequisites

- Docker Desktop installed and running
- Docker Compose v3.8+
- At least 4GB RAM allocated to Docker
- Git (for cloning dependencies)

## Quick Start

### 1. Build the Docker Image

```bash
# Build all stages
npm run docker:build

# Or build development stage only
npm run docker:build:dev
```

### 2. Start the Local Blockchain Node

```bash
# Start Anvil node (exposes ports 8545 and 8546)
npm run docker:node

# Or using docker-compose directly
docker-compose up contracts
```

The node will be available at:
- **RPC**: `http://localhost:8545`
- **WebSocket**: `ws://localhost:8546` (if configured)

### 3. Run Tests

```bash
# Run all tests
npm run docker:test

# Or with verbose output
docker-compose run --rm test forge test -vvv
```

### 4. Compile Contracts

```bash
# Compile all contracts
npm run docker:compile
```

## Docker Services

The `docker-compose.yml` defines several services:

### `contracts` (Default)
- **Purpose**: Local blockchain node (Anvil)
- **Ports**: 8545 (RPC), 8546 (WebSocket)
- **Command**: `anvil --host 0.0.0.0 --port 8545`
- **Usage**: `docker-compose up contracts`

### `dev`
- **Purpose**: Development environment with live reload
- **Volumes**: Mounts entire project for live editing
- **Usage**: `docker-compose --profile dev up -d dev`
- **Access**: `docker-compose exec dev /bin/bash`

### `test`
- **Purpose**: Run Foundry tests
- **Depends on**: `contracts` service
- **Usage**: `docker-compose run --rm test`

### `compile`
- **Purpose**: Compile contracts
- **Usage**: `docker-compose run --rm compile`

## Building Images

### Build All Stages

```bash
docker build -t project-rebuild:latest .
```

This builds:
- `base`: Base image with Node.js and Foundry
- `builder`: Compiles contracts
- `development`: Development environment
- `production`: Production-ready image

### Build Specific Stage

```bash
# Development stage
docker build --target development -t project-rebuild:dev .

# Production stage
docker build --target production -t project-rebuild:prod .
```

### Build with Custom Arguments

```bash
docker build \
  --build-arg NODE_VERSION=20 \
  -t project-rebuild:latest .
```

## Running Services

### Start Blockchain Node

```bash
# Using npm script
npm run docker:node

# Using docker-compose
docker-compose up contracts

# Run in background
docker-compose up -d contracts

# View logs
docker-compose logs -f contracts
```

### Start Development Environment

```bash
# Start dev service
npm run docker:dev

# Access shell
npm run docker:shell

# Or directly
docker-compose exec dev /bin/bash
```

### Stop Services

```bash
# Stop all services
npm run docker:down

# Stop and remove volumes
npm run docker:clean
```

## Testing

### Run All Tests

```bash
# Using npm script
npm run docker:test

# Using docker-compose
docker-compose run --rm test

# With verbose output
docker-compose run --rm test forge test -vvv
```

### Run Specific Test File

```bash
docker-compose run --rm test forge test --match-path test/mint/Mint.t.sol
```

### Run Tests with Coverage

```bash
docker-compose run --rm test forge coverage
```

### Run Tests in Interactive Mode

```bash
# Start dev container
docker-compose run --rm dev /bin/bash

# Inside container, run tests
forge test
forge test -vvv
forge coverage
```

## Compilation

### Compile All Contracts

```bash
# Using npm script
npm run docker:compile

# Using docker-compose
docker-compose run --rm compile

# With specific options
docker-compose run --rm compile forge build --sizes
```

### Compile in Development Container

```bash
# Access dev container
docker-compose run --rm dev /bin/bash

# Compile inside
forge build
```

## Development Workflow

### 1. Start Services

```bash
# Terminal 1: Start blockchain node
npm run docker:node

# Terminal 2: Start dev environment
npm run docker:dev
```

### 2. Access Development Container

```bash
# Get shell access
npm run docker:shell

# Or
docker-compose exec dev /bin/bash
```

### 3. Install Dependencies

Inside the container:

```bash
# Install Foundry dependencies
forge install OpenZeppelin/openzeppelin-contracts --no-commit
forge install smartcontractkit/chainlink-brownie-contracts --no-commit

# Install Node dependencies (if any)
npm install
```

### 4. Develop with Live Reload

Since volumes are mounted, changes to files are immediately reflected:

```bash
# Edit contracts in your IDE
# Changes are visible in container

# Compile
forge build

# Test
forge test
```

### 5. Run Deployment Scripts

```bash
# Inside dev container
forge script contracts/deployments/DeployMocks.s.sol:DeployMocks \
  --rpc-url http://contracts:8545 \
  --broadcast
```

## Deployment

### Deploy to Local Node

```bash
# Start node
docker-compose up -d contracts

# Deploy using dev container
docker-compose run --rm dev forge script \
  contracts/deployments/DeployProjectRebuild.s.sol:DeployProjectRebuild \
  --rpc-url http://contracts:8545 \
  --broadcast
```

### Deploy to Testnet/Mainnet

```bash
# Set environment variables
export PRIVATE_KEY=your_private_key
export FOUNDER_WALLET=0x...
export VRF_SUBSCRIPTION_ID=1

# Deploy
docker-compose run --rm dev forge script \
  contracts/deployments/DeployProjectRebuild.s.sol:DeployProjectRebuild \
  --rpc-url $RPC_URL \
  --broadcast \
  --verify
```

## Advanced Usage

### Custom Docker Compose Commands

```bash
# Run specific command in dev container
docker-compose run --rm dev forge fmt
docker-compose run --rm dev forge snapshot
docker-compose run --rm dev cast --version

# Run with environment variables
docker-compose run --rm -e PRIVATE_KEY=0x... dev forge script ...
```

### Access Container Logs

```bash
# View all logs
docker-compose logs

# View specific service logs
docker-compose logs contracts
docker-compose logs dev

# Follow logs
docker-compose logs -f contracts
```

### Execute Commands in Running Container

```bash
# Execute command in running container
docker-compose exec dev forge test

# Get interactive shell
docker-compose exec dev /bin/bash
```

### Clean Up

```bash
# Stop and remove containers
docker-compose down

# Remove volumes (clears cache, lib, out)
docker-compose down -v

# Full cleanup (removes images too)
npm run docker:clean
```

## Environment Variables

Create a `.env` file in the project root:

```bash
PRIVATE_KEY=your_private_key
FOUNDER_WALLET=0x...
VRF_SUBSCRIPTION_ID=1
VRF_KEY_HASH=0x...
BASE_URI=https://api.projectrebuild.com/metadata/
BASE_IMAGE_URI=https://api.projectrebuild.com/images/
RPC_URL=http://contracts:8545
```

These are automatically loaded by docker-compose.

## Troubleshooting

### Port Already in Use

```bash
# Check what's using the port
lsof -i :8545

# Kill the process or change port in docker-compose.yml
```

### Container Won't Start

```bash
# Check logs
docker-compose logs contracts

# Rebuild image
docker-compose build --no-cache contracts

# Remove and recreate
docker-compose down -v
docker-compose up contracts
```

### Dependencies Not Found

```bash
# Reinstall Foundry dependencies
docker-compose run --rm dev forge install OpenZeppelin/openzeppelin-contracts --no-commit
docker-compose run --rm dev forge install smartcontractkit/chainlink-brownie-contracts --no-commit
```

### Permission Issues

```bash
# Fix file permissions
sudo chown -R $USER:$USER .

# Or run with user mapping in docker-compose.yml
```

### Out of Memory

```bash
# Increase Docker memory limit in Docker Desktop
# Settings > Resources > Memory (recommend 4GB+)
```

### Network Issues

```bash
# Recreate network
docker-compose down
docker network prune
docker-compose up
```

## Best Practices

1. **Use Volumes**: Always mount project directory for live reload
2. **Clean Regularly**: Run `npm run docker:clean` periodically
3. **Use Profiles**: Use service profiles to avoid starting unnecessary services
4. **Environment Variables**: Never commit `.env` files
5. **Health Checks**: Wait for services to be healthy before running tests
6. **Resource Limits**: Set appropriate memory/CPU limits in production

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Test

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Run tests
        run: |
          docker-compose up -d contracts
          docker-compose run --rm test
```

## Production Deployment

For production deployments:

1. Use production stage: `docker build --target production`
2. Set environment variables securely
3. Use secrets management (Docker secrets, AWS Secrets Manager, etc.)
4. Enable health checks
5. Set resource limits
6. Use read-only filesystem where possible

## Additional Resources

- [Docker Documentation](https://docs.docker.com/)
- [Docker Compose Documentation](https://docs.docker.com/compose/)
- [Foundry Documentation](https://book.getfoundry.sh/)
- [Anvil Documentation](https://book.getfoundry.sh/anvil/)

## Support

For issues or questions:
1. Check logs: `docker-compose logs`
2. Review this guide
3. Check project README.md
4. Open an issue on GitHub

