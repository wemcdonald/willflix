FROM denoland/deno:alpine-2.1.4

WORKDIR /app

COPY deno.json /app/deno.json
COPY index.ts /app/index.ts

# Pre-cache npm/jsr deps so cold start is fast and image is reproducible.
RUN deno cache --node-modules-dir=auto /app/index.ts

EXPOSE 8000

CMD ["deno", "run", \
     "--allow-net", \
     "--allow-env", \
     "--allow-read=/app,/run/secrets", \
     "--node-modules-dir=auto", \
     "/app/index.ts"]
