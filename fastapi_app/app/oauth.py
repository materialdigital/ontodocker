from authlib.integrations.starlette_client import OAuth
from urllib.parse import quote
import  os
import hashlib
import secrets
from dependencies import get_db_session
from db import get_enabled_sso_providers

class SSOAuth:
    
    def __init__(self) -> None:
        session = next(get_db_session())
        self.token = None
        self.oauth = OAuth()
        self.current_provider = None
        self.registered_providers = []
        for sso_provider in get_enabled_sso_providers(session):
            self.registered_providers.append(self.generate_provider_name(sso_provider))
            if sso_provider.type == "keycloak" or sso_provider.type == "orcid":
                self.register_oidc_provider(sso_provider)

    @classmethod
    def instance(cls):
        if cls._instance is None:
            print('Creating new instance')
            cls._instance = cls.__new__(cls)
        return cls._instance

    def get_registered_providers(self):
        return self.registered_providers

    def generate_provider_name(self, provider):
        return hashlib.sha256(f"{provider.id}{provider.name}{provider.client_id}{provider.client_secret}{provider.server_metadata_url}".encode()).hexdigest()
    
    def register_oidc_provider(self, sso_provider):
        self.oauth.register(
            name=self.generate_provider_name(sso_provider),
            client_id=sso_provider.client_id,
            client_secret=sso_provider.client_secret,
            server_metadata_url=sso_provider.server_metadata_url,
            client_kwargs={'scope': sso_provider.scope},
            authorize_state=hashlib.sha256(os.environ.get("JWT_SECRET_KEY", secrets.token_urlsafe(32)).encode()).hexdigest()
        )


    def get_oauth_client(self, provider):
        self.current_provider = provider
        return self.oauth.create_client(provider)
    
    async def authorize_and_get_oauth_token(self, request):
        self.token = await self.oauth.create_client(self.current_provider).authorize_access_token(request)
        return self.token
    
    def get_logout_url(self, request):
        base_url = f'{request.url.scheme}://{request.url.netloc}/'
        if self.current_provider == "keycloak":
            end_session_endpoint = self.oauth.keycloak.server_metadata.get("end_session_endpoint", None)
            if end_session_endpoint and "id_token" in self.token:

                # id_token_hint is used also as a CSRF token to allow skip the logout confirmation screen
                # use --spi-login-protocol-openid-connect-legacy-logout-redirect-uri=true in docker-compose.yml
                # if redirect_uri parameter is used
                client_id = os.environ.get("OIDC_CLIENT_ID", "")
                id_token = self.token["id_token"]
                return f"{end_session_endpoint}?client_id={client_id}&id_token_hint={id_token}&post_logout_redirect_uri={quote(base_url)}"
                
        
        return "/"

