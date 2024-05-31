FROM quay.io/keycloak/keycloak:22.0.0

# Configure a database vendor
ENV KC_DB=postgres
ENV KC_DB_URL_HOST=keycloak-db
ENV KC_DB_URL_DATABASE=keycloak
ENV KC_DB_USERNAME=keycloak

# KC_DB_PASSWORD must be the same as POSTGRES_PASSWORD in docker-compose.yml
ENV KC_DB_PASSWORD=changeme
ENV KC_DB_SCHEMA=public

# configure keycloak admin credentials for login
ENV KEYCLOAK_ADMIN=admin
ENV KEYCLOAK_ADMIN_PASSWORD=changeme

# change to Ipv4 adress if you got Localhost Refused to Connect  error
ENV KC_HOSTNAME_URL=http://localhost:8080


