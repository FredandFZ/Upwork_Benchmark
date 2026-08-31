.PHONY: help format format-check build test script validate clean

help:
	@printf '%s\n' \
		'make format        Format Solidity sources' \
		'make format-check  Check Solidity formatting' \
		'make build         Compile the repository' \
		'make test          Run the smoke test' \
		'make script        Simulate the deployment entry point' \
		'make validate      Run all validation steps' \
		'make clean         Remove generated Foundry artifacts'

format:
	forge fmt

format-check:
	forge fmt --check

build:
	forge build

test:
	forge test -vv

script:
	forge script script/DeployEnvironment.s.sol:DeployEnvironment

validate:
	./scripts/validate.sh

clean:
	rm -rf cache out broadcast
