FROM node:22-slim

RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && \
    rm -rf /var/lib/apt/lists/* && \
    git config --global url."https://github.com/".insteadOf "ssh://git@github.com/" && \
    npm install -g openclaw@latest

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

VOLUME ["/home/node/.openclaw"]

ENTRYPOINT ["/entrypoint.sh"]
