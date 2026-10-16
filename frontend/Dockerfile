FROM node:24-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN --mount=type=secret,id=build_ca,required=false if [ -s /run/secrets/build_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/build_ca; fi; npm ci
COPY . .
ARG VITE_MAP_STYLE
ARG VITE_GEOCODER_URL
ENV VITE_MAP_STYLE=$VITE_MAP_STYLE VITE_GEOCODER_URL=$VITE_GEOCODER_URL
RUN npm run build
FROM nginx:1.28-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
RUN chmod -R a+rX /usr/share/nginx/html /etc/nginx/conf.d
EXPOSE 80
