FROM node:20-alpine AS builder
RUN apk add --no-cache git python3 make g++
WORKDIR /src
RUN git clone --depth=1 --recurse-submodules --shallow-submodules https://github.com/curiousdannii/parchment.git .
RUN npm install && npm run build

FROM nginx:alpine
COPY --from=builder /src/dist/web/ /usr/share/nginx/html/
COPY --from=builder /src/dist/fonts/ /usr/share/nginx/html/fonts/
COPY index.html /usr/share/nginx/html/index.html
COPY play.html /usr/share/nginx/html/play.html
COPY nginx.conf /etc/nginx/conf.d/default.conf
