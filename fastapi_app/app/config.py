import json
import os
import secrets
from functools import lru_cache

from fastapi_jwt_auth import AuthJWT
from pydantic import BaseSettings

user_dir = "/data/user/"
web_dir = "/data/web/"

# Ensure folders exist
os.makedirs(user_dir, exist_ok=True)
os.makedirs(web_dir, exist_ok=True)

class Settings(BaseSettings):
    SQLALCHEMY_DATABASE_URI: str = f"sqlite:///{os.path.join(user_dir, 'user.db')}"

    JWT_SECRET_KEY: str = os.environ.get("JWT_SECRET_KEY", str(secrets.token_urlsafe(16)))#  # use openssl rand -hex 48
    JWT_DEFAULT_DAYS_VALID: int = int(os.environ.get("JWT_DEFAULT_DAYS_VALID", "1"))
    #authjwt_secret_key = JWT_SECRET_KEY

    # roles that are allowed to access, go to Keycloak console to configure if needed
    KEYCLOAK_ADMIN_ROLES: list = [x.strip() for x in os.environ.get("KEYCLOAK_ROLES_ADMIN", "").split(",")]
    KEYCLOAK_READWRITE_ROLES: list = [x.strip() for x in os.environ.get("KEYCLOAK_ROLES_RW", "").split(",")]
    KEYCLOAK_READONLY_ROLES: list = [x.strip() for x in os.environ.get("KEYCLOAK_ROLES_RO", "").split(",")]
    KEYCLOAK_REQUIRED_ROLES: list = KEYCLOAK_ADMIN_ROLES + KEYCLOAK_READWRITE_ROLES + KEYCLOAK_READONLY_ROLES
    ADMIN_EMAIL: str = os.environ.get("ADMIN_EMAIL", "")  # admin email, used for API Key authenticate

@AuthJWT.load_env
def get_config():
    return Settings()

class KeycloakSettings(BaseSettings):
    host: str = os.environ.get("KEYCLOAK_HOST", "")  # This is your Keycloak URL (use http://<IPv4 address>:8080) (Don't use VPN)
    realm: str = os.environ.get("KEYCLOAK_REALM", "") # This is your Keycloak Realm name, default is "master"
    client_id: str = os.environ.get("KEYCLOAK_CLIENT_ID", "") # This is your Keycloak client id that you have previously created
    client_secret: str = os.environ.get("KEYCLOAK_CLIENT_SECRET", "") # This is your Keycloak client secret
    app_uri: str = os.environ.get("APP_URI", "") # This is your application URL
    token_uri: str = f"{host}/realms/{realm}/protocol/openid-connect/token"  # http://<IPv4 address>:8080/realms/master/protocol/openid-connect/token
    scope: str = "openid email profile"
    verify: bool = True


class FusekiSettings(BaseSettings):
    FUSEKI_ADMIN_USER = os.environ.get("FUSEKI_ADMIN_USER", "")
    FUSEKI_ADMIN_PW = os.environ.get("FUSEKI_ADMIN_PW", "") 
    credentials: str = f"{FUSEKI_ADMIN_USER}:{FUSEKI_ADMIN_PW}"  # this is Fuseki UI admin credentials, required when using secoresearch/fuseki


@lru_cache()
def get_settings():
    return Settings()


@lru_cache()
def get_keycloak_settings():
    return KeycloakSettings()


@lru_cache()
def get_fuseki_settings():
    return FusekiSettings()
