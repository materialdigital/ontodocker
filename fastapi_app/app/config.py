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
    SQLALCHEMY_DATABASE_URI: str = f"sqlite:///{os.path.join(user_dir, 'ontodocker.db.sqlite')}"

    JWT_SECRET_KEY: str = os.environ.get("JWT_SECRET_KEY", str(secrets.token_urlsafe(16)))#  # use openssl rand -hex 48
    JWT_DEFAULT_DAYS_VALID: int = int(os.environ.get("JWT_DEFAULT_DAYS_VALID", "1"))
    #authjwt_secret_key = JWT_SECRET_KEY
    
    OIDC_ADMIN_ROLE: str = "admin"
    OIDC_READWRITE_ROLE: str = "rw"
    OIDC_READONLY_ROLE: str = "ro"
    OIDC_REQUIRED_ROLES: list = [OIDC_ADMIN_ROLE, OIDC_READWRITE_ROLE, OIDC_READONLY_ROLE]

@AuthJWT.load_env
def get_config():
    return Settings()

class FusekiSettings(BaseSettings):
    FUSEKI_ADMIN_USER = os.environ.get("FUSEKI_ADMIN_USER", "")
    FUSEKI_ADMIN_PW = os.environ.get("FUSEKI_ADMIN_PW", "") 
    credentials: str = f"{FUSEKI_ADMIN_USER}:{FUSEKI_ADMIN_PW}"  # this is Fuseki UI admin credentials, required when using secoresearch/fuseki


@lru_cache()
def get_settings():
    return Settings()


@lru_cache()
def get_fuseki_settings():
    return FusekiSettings()
