FROM nginx:1.27-alpine

# Remove default configuration and static files
RUN rm -rf /etc/nginx/conf.d/* /usr/share/nginx/html/*

# Copy high-performance load balancer configuration
COPY nginx.conf /etc/nginx/nginx.conf

# Copy fallback / status page
COPY html /usr/share/nginx/html

# Expose ports: 80 (HTTP), 8000 (Gateway alias), 8080 (Secondary alias), 443 (HTTPS)
EXPOSE 80 8000 8080 443

HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
    CMD wget --quiet --tries=1 --spider http://127.0.0.1:80/lb-health || exit 1

CMD ["nginx", "-g", "daemon off;"]
