import json
import os
from functools import lru_cache
from pydantic import BaseSettings

user_dir = "/data/user/"
web_dir = "/data/web/"

# Ensure folders exist
os.makedirs(user_dir, exist_ok=True)
os.makedirs(web_dir, exist_ok=True)

class Settings(BaseSettings):
    PROPERTY_FILE_PATH: str = os.path.join(web_dir, "prop_simple_demo.json")  # example data

    SQLALCHEMY_DATABASE_URI: str = f"sqlite:///{os.path.join(user_dir, 'user.db')}"

    JWT_SECRET_KEY: str = "BvaH6zRim4QXgAgUS7cJRQ"  # TODO change this. Use secrets.token_urlsafe(16) to generate
    JWT_DAYS_VALID: int = 90

    # TODO roles that are allowed to access, go to Keycloak console to configure if needed
    KEYCLOAK_REQUIRED_ROLES = ["admin", "App-admin", "App-insider", "App-guest"]
    ADMIN_EMAIL = ["ya-fan.chen@uni-jena.de"]  # admin email, used for API Key authenticate


# TODO don't forget to start the Keycloak container first and then start Fast Ontodocker container afterwards
class KeycloakSettings(BaseSettings):
    host: str = "http://<IPv4 address>:8080"  # TODO This is your Keycloak URL (use http://<IPv4 address>:8080) (Don't use VPN)
    realm: str = "master"  # TODO This is your Keycloak Realm name, default is "master"
    client_id: str = "glass"  # TODO This is your Keycloak client id that you have previously created
    client_secret: str = "7hOqSm7JpKjm3DphZrn5GLtFoGtxn1FX"  # TODO This is your Keycloak client secret
    app_uri: str = "http://fastapi:80"  # This is your application URL
    token_uri: str = "http://<IPv4 address>:8080/realms/master/protocol/openid-connect/token"  # TODO http://<IPv4 address>:8080/realms/master/protocol/openid-connect/token
    scope: str = "openid email profile"
    verify: bool = True


class FusekiSettings(BaseSettings):
    credentials: str = "admin:changeme"  # TODO this is Fuseki UI admin credentials, required when using secoresearch/fuseki


@lru_cache()
def get_settings():
    return Settings()


@lru_cache()
def get_keycloak_settings():
    return KeycloakSettings()


@lru_cache()
def get_fuseki_settings():
    return FusekiSettings()


def load_property_tree(settings):
    with open(settings.PROPERTY_FILE_PATH, "r", encoding="utf-8") as f:
        prop_mapping_dict = json.load(f)
        return prop_mapping_dict


class Data(BaseSettings):
    property_data: dict = load_property_tree(get_settings())


@lru_cache()
def get_data():
    return Data()
