"""
modified from https://github.com/prokie/fastapi-oidc-auth/tree/master
"""
import inspect
import json
import logging
from base64 import b64encode
from functools import wraps
from json.decoder import JSONDecodeError
from urllib.parse import quote

import jwt
import requests
from fastapi import Request, Depends
from jwt.exceptions import DecodeError, InvalidTokenError
from starlette.responses import RedirectResponse

from .exceptions import OpenIDConnectException

logger = logging.getLogger(__name__)

class OpenIDConnect:
    well_known_pattern = "{}/realms/{}/.well-known/openid-configuration"

    def __init__(
            self,
            host: str,
            realm: str,
            app_uri: str,
            client_id: str,
            client_secret: str,
            scope: str = "openid email profile",
            verify: bool = True,
    ) -> None:
        self.app_uri = app_uri
        self.scope = scope
        self.client_id = client_id
        self.client_secret = client_secret
        self.verify = verify
        endpoints = self.to_dict_or_raise(
            requests.get(self.well_known_pattern.format(host, realm), verify=self.verify)
        )
        self.issuer = endpoints.get("issuer")
        self.authorization_endpoint = endpoints.get("authorization_endpoint")
        self.token_endpoint = endpoints.get("token_endpoint")
        self.userinfo_endpoint = endpoints.get("userinfo_endpoint")
        self.jwks_uri = endpoints.get("jwks_uri")
        self.logout_endpoint = endpoints.get("end_session_endpoint")
        self.refresh_token_endpoint = endpoints.get("refresh_token_endpoint")
        # new
        self.introspection_endpoint = endpoints.get("introspection_endpoint")

    def authenticate(self, code: str, callback_uri: str, get_user_info: bool = False) -> dict:
        auth_token = self.get_auth_token(code, callback_uri)
        id_token = auth_token.get("id_token")
        try:
            alg = jwt.get_unverified_header(id_token).get("alg")
        except DecodeError:
            logging.warning("Error getting unverified header in jwt.")
            raise OpenIDConnectException
        validated_token = self.obtain_validated_token(alg, id_token)
        if not get_user_info:
            return validated_token
        user_info = self.get_user_info(auth_token.get("access_token"))
        self.validate_sub_matching(validated_token, user_info)
        return user_info

    def logout(self, request: Request, confirmation: bool = False) -> RedirectResponse:
        callback_uri = f"http://{request.url.netloc}"
        # callback_uri = f"https://{request.url.netloc}"
        if confirmation:
            return RedirectResponse(
                f"{self.logout_endpoint}?response_type=code&scope={self.scope}&client_id={self.client_id}&"
                f"redirect_uri={quote(callback_uri)}"
            )
        else:
            auth_token = self.get_id_token()
            id_token = auth_token.get("id_token")
            print(f"{id_token = }")

            # id_token_hint is used also as a CSRF token to allow skip the logout confirmation screen
            # use --spi-login-protocol-openid-connect-legacy-logout-redirect-uri=true in docker-compose.yml
            # if redirect_uri parameter is used
            return RedirectResponse(
                f"{self.logout_endpoint}?client_id={self.client_id}&id_token_hint={id_token}&"
                f"post_logout_redirect_uri={quote(callback_uri)}"
            )

    def get_id_token(self) -> dict:
        data = {
            "grant_type": "client_credentials",
            "client_secret": self.client_secret,
            "client_id": self.client_id,
            "scope": self.scope
        }
        response = requests.post(
            self.token_endpoint, data=data, verify=self.verify
        )
        return self.to_dict_or_raise(response)

    def get_auth_redirect_uri(self, callback_uri: str) -> str:
        return "{}?response_type=code&scope={}&client_id={}&redirect_uri={}".format(  # noqa
            self.authorization_endpoint,
            self.scope,
            self.client_id,
            quote(callback_uri),
        )

    def get_auth_token(self, code: str, callback_uri: str) -> dict:
        authstr = "Basic " + b64encode(
            f"{self.client_id}:{self.client_secret}".encode("utf-8")
        ).decode("utf-8")
        headers = {"Authorization": authstr}
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": callback_uri,
        }
        response = requests.post(
            self.token_endpoint, data=data, headers=headers, verify=self.verify
        )
        return self.to_dict_or_raise(response)

    def obtain_validated_token(self, alg: str, id_token: str) -> dict:
        if alg == "HS256":
            try:
                return jwt.decode(
                    id_token,
                    self.client_secret,
                    algorithms=["HS256"],
                    audience=self.client_id,
                )
            except InvalidTokenError:
                logger.error("An error occurred while decoding the id_token using HS256 Signature Algorithm")
                raise OpenIDConnectException("An error occurred while decoding the id_token using RS256 Signature Algorithm")
        elif alg == "RS256":
            response = requests.get(self.jwks_uri, verify=self.verify)
            web_key_sets = self.to_dict_or_raise(response)
            jwks = web_key_sets.get("keys")
            public_key = self.extract_token_key(jwks, id_token)
            try:
                return jwt.decode(
                    id_token,
                    key=public_key,
                    algorithms=["RS256"],
                    audience=self.client_id,
                )
            except InvalidTokenError:
                logger.error("An error occurred while decoding the id_token using RS256 Signature Algorithm")
                raise OpenIDConnectException("An error occurred while decoding the id_token using RS256 Signature Algorithm")
        else:
            raise OpenIDConnectException("Unsupported jwt algorithm found.")

    def extract_token_key(self, jwks: dict, id_token: str) -> str:
        public_keys = {}
        for jwk in jwks:
            kid = jwk.get("kid")
            if not kid:
                continue
            public_keys[kid] = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(jwk))
        try:
            kid = jwt.get_unverified_header(id_token).get("kid")
        except DecodeError:
            logger.warning("kid could not be extracted.")
            raise OpenIDConnectException("kid could not be extracted.")
        return public_keys.get(kid)

    def get_user_info(self, access_token: str) -> dict:
        bearer = "Bearer {}".format(access_token)
        headers = {"Authorization": bearer}
        response = requests.get(self.userinfo_endpoint, headers=headers, verify=self.verify)
        return self.to_dict_or_raise(response)

    @staticmethod
    def validate_sub_matching(token: dict, user_info: dict) -> None:
        token_sub = ""  # nosec
        if token:
            token_sub = token.get("sub")
        if token_sub != user_info.get("sub") or not token_sub:
            logger.warning("Subject mismatch error.")
            raise OpenIDConnectException("Subject mismatch error.")

    @staticmethod
    def to_dict_or_raise(response: requests.Response) -> dict:
        if response.status_code != 200:
            logger.error(f"Returned with status {response.status_code}.")
            raise OpenIDConnectException(f"Status code {response.status_code} for {response.url}.")
        try:
            return response.json()
        except JSONDecodeError:
            logger.error("Unable to decode json.")
            raise OpenIDConnectException("Was not able to retrieve data from the response.")

    def require_login(self, view_func):
        @wraps(view_func)
        async def decorated(request: Request, get_user_info: bool = False, *args, **kwargs):
            callback_uri = f"http://{request.url.netloc}{request.url.path}"  # noqa
            # callback_uri = f"https://{request.url.netloc}{request.url.path}"  # noqa

            # print(f"\n############\n{request.url = }\n############\n")
            print(f"\n############\n{callback_uri = }\n############\n")
            # print(f"\n############\n{str(request.url) = }\n############\n")

            redirect_param = request.query_params.get(
                "redirect")  # Get the redirect parameter from the query params

            if redirect_param:
                callback_uri += f"?redirect={quote(redirect_param)}"

            code = request.query_params.get("code")
            # print(f"\n############\n{code = }\n############\n")
            if not code:
                print(f"{self.get_auth_redirect_uri(callback_uri) = }")
                return RedirectResponse(self.get_auth_redirect_uri(callback_uri))
            try:
                user_info = self.authenticate(code, callback_uri, get_user_info=get_user_info)

                # user_role = self.get_user_role(create_keycloak_apikey())
                # request.__setattr__("user_role", user_role)

                request.__setattr__("user_info", user_info)
                # return await view_func(request, *args, **kwargs)
                if inspect.iscoroutinefunction(view_func):  # Check if view_func is async
                    return await view_func(request, *args, **kwargs)
                else:
                    return view_func(request, *args, **kwargs)
            except OpenIDConnectException:
                return RedirectResponse(self.get_auth_redirect_uri(callback_uri))

        return decorated
