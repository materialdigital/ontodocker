import inspect
from functools import wraps

import httpx
import jwt
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.requests import Request
from fastapi.responses import JSONResponse
from sqlmodel import Session
from urllib.parse import quote, urlparse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from __init__ import engine, templates
from libs.prokie_fastapi_oidc_auth.auth import OpenIDConnect
from config import get_settings, get_keycloak_settings, Settings

from utils import flash

keycloak_setting = get_keycloak_settings()

oidc = OpenIDConnect(keycloak_setting.host, keycloak_setting.realm, keycloak_setting.app_uri,
                     keycloak_setting.client_id, keycloak_setting.client_secret,
                     keycloak_setting.scope, keycloak_setting.verify)

security = HTTPBearer(
    description="Enter the API key (you will find it on the <a target='_blank' href='/'>Homepage</a> after login)")


async def verify_token(request: Request, credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    print(f"\n####\n{token = }\n####\n")
    try:
        decoded_jwt = jwt.decode(token, get_settings().JWT_SECRET_KEY, audience=request.client.host,
                                 algorithms=["HS256"],
                                 options={"verify_signature": True})
        # print(f"\n####\n{decoded_jwt = }\n####\n")
        return decoded_jwt
    except jwt.exceptions.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Token unauthorized. {e}")


async def admin_required(decoded_jwt: Annotated[dict, Depends(verify_token)],
                         settings: Annotated[Settings, Depends(get_settings)]):
    email = decoded_jwt.get('email')
    role = decoded_jwt.get('role', [])

    return email == settings.ADMIN_EMAIL or any(role_check in role for role_check in ["admin", "App-admin"])


async def check_auth(request: Request):
    if not request.session.get("name"):
        if request.method == "GET":
            raise HTTPException(
                status_code=status.HTTP_307_TEMPORARY_REDIRECT,
                headers={'Location': f'/login'})
        if request.method == "POST":
            # applies only to post requests that reload the page, non-reloading requests (using Axios) are not applicable
            # use return JSONResponse(content="Not authenticated", status_code=401) in those endpoints using axios in frontend
            redirect_url = request.headers.get('Referer', '/')  # get the url before redirection
            raise HTTPException(
                status_code=status.HTTP_303_SEE_OTHER,  # redirect a POST request to a GET resource
                headers={'Location': f'/login?redirect={quote(redirect_url)}'})
    return True


async def get_user_role(request: Request):
    print(f"{request.session.get('role') = }")
    return request.session.get('role')


async def admin_role(request: Request, role=Depends(get_user_role)):
    # if role is None or (role != "admin" and role != "App-admin"):
    if role is None or all(role_check not in role for role_check in ["admin", "App-admin"]):
        if request.method == "GET":
            raise HTTPException(status_code=403, detail="Access forbidden (admin only for now)")
        if request.method == "POST":
            # applies only to post requests that reload the page, non-reloading requests (using Axios) are not applicable
            # use return JSONResponse(content="Access forbidden", status_code=403) in those endpoints using axios in frontend
            redirect_url = request.headers.get('Referer', '/')  # get the url before redirection
            # Get the path component from the URL
            parsed_url = urlparse(redirect_url)
            path = parsed_url.path

            # Encode only the path component
            encoded_path = quote(path)

            # Build the redirect URL using the encoded path
            redirect_url = f"{parsed_url.scheme}://{parsed_url.netloc}{encoded_path}"

            flash(request,
                  message="Access forbidden (admin only for now)",
                  category="warning")
            raise HTTPException(
                status_code=status.HTTP_303_SEE_OTHER,  # redirect a POST request to a GET resource
                headers={'Location': redirect_url})
    return True


def require_role():  # required_roles: List[str]
    """
    keycloak role to be defined in app.config("KEYCLOAK_REQUIRED_ROLE")
    role has to be in user_info as "realm_access": {"roles": [str]}
    inspired by flask_oidc.OpenIDConnect.require_keycloak_role
    https://github.com/puiterwijk/flask-oidc/blob/master/flask_oidc/__init__.py#L502

    modify from https://git.material-digital.de/apps/ontodocker/-/blob/master/flask_app/app/auth.py
    to allow method to accept list of required roles, e.g.:
    required_roles = ["admin", "App-admin", "App-insider", "App-guest"]

    """

    def wrapper(view_func):
        @wraps(view_func)
        async def decorated(request: Request, *args, **kwargs):

            roles = request.user_info.get('realm_access', []).get('roles', [])
            # roles = request.session["role"]
            required_roles = get_settings().KEYCLOAK_REQUIRED_ROLES
            print(f"\n################{roles = }\n{required_roles = }################\n")

            if any(role in roles for role in required_roles):
                # have to add "Realm Roles" to ID token in Keycloak console panel in order to use "realm_access.roles"
                if inspect.iscoroutinefunction(view_func):  # Check if view_func is async
                    return await view_func(request, *args, **kwargs)
                else:
                    return view_func(request, *args, **kwargs)
            else:
                return templates.TemplateResponse("403-visitor.html", {"request": request}, status_code=403)

        return decorated

    return wrapper


def get_session():
    with Session(engine) as session:
        yield session


async def get_client():
    # timeout = httpx.Timeout(timeout=600.0)
    timeout = httpx.Timeout(timeout=None)  # Disable all timeouts by default
    # create a new client for each request
    async with httpx.AsyncClient(timeout=timeout) as client:
        # yield the client to the endpoint function
        yield client
        # close the client when the request is done