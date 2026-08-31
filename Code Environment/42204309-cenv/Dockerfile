ARG FOUNDRY_IMAGE=ghcr.io/foundry-rs/foundry:stable
FROM ${FOUNDRY_IMAGE}

ENTRYPOINT []
WORKDIR /workspace
COPY . .

RUN forge build && forge test

CMD ["forge", "test", "-vv"]
