import inspect
from functools import wraps

import httpx
import os
import jwt
from typing import Annotated
from datetime import datetime, timedelta

from fastapi import Depends, HTTPException, status
from fastapi.requests import Request
from fastapi.responses import JSONResponse
from sqlmodel import Session
from urllib.parse import quote, urlparse
from fastapi.security import  HTTPBearer
from __init__ import engine, templates
from libs.prokie_fastapi_oidc_auth.auth import OpenIDConnect
from config import get_settings, get_keycloak_settings, Settings
from typing import Optional
from utils import flash

keycloak_setting = get_keycloak_settings()

oidc = OpenIDConnect(keycloak_setting.host, keycloak_setting.realm, keycloak_setting.app_uri,
                     keycloak_setting.client_id, keycloak_setting.client_secret,
                     keycloak_setting.scope, keycloak_setting.verify)

security = HTTPBearer(
    description="Enter the API key (you will find it on the <a target='_blank' href='/'>Homepage</a> after login)")

allow_unauthorized_readonly_api_access = os.environ.get("ALLOW_UNAUTHORIZED_READONLY_API_ACCESS", "False").lower() == "true"
allow_unauthorized_readonly_ui_access = os.environ.get("ALLOW_UNAUTHORIZED_READONLY_UI_ACCESS", "False").lower() == "true"

def create_apikey(name: str, email: str, role: list, validDays: int, request: Request,
                             settings: Annotated[Settings, Depends(get_settings)]):
    issued_at = datetime.now()
    expires_at = issued_at + timedelta(days=validDays)
    claim_set = {
        "iss": "MaterialDigital",  # Identifier (or, name) of the server or system issuing the token
        "iat": issued_at.timestamp(),  # Date/time when the token was issued
        "exp": expires_at.timestamp(),  # Date/time at which point the token is no longer valid
        "aud": "ontodocker",
        "name": name,  # The full name of the user
        "email": email,  # The email address of the user
        "role": role  # The role of the user
    }
    encoded_jwt = jwt.encode(payload=claim_set,
                             key=settings.JWT_SECRET_KEY,
                             algorithm='HS256')
    return encoded_jwt

def decode_token(token: str):
    decoded_jwt = jwt.decode(token, get_settings().JWT_SECRET_KEY, options={"verify_aud": False, "verify_signature": False}, algorithms=["HS256"])
    # print(f"\n####\n{decoded_jwt = }\n####\n")
    return decoded_jwt

async def get_optional_token(request: Request) -> Optional[str]:
    if "Authorization" in request.headers:
        auth = request.headers["Authorization"]
        if auth.startswith("Bearer "):
            return auth[len("Bearer "):]
    return None

async def verify_readonly(request: Request, 
                          settings: Annotated[Settings, Depends(get_settings)], 
                          token: Optional[str] = Depends(get_optional_token)):
    if allow_unauthorized_readonly_api_access:
        return True
    if not token:
        raise HTTPException(status_code=401, detail=f"No token offered.")
    print(f"\n####\n{token = }\n####\n")
    try:
        decoded_jwt = jwt.decode(token, get_settings().JWT_SECRET_KEY, audience="ontodocker",
                                 algorithms=["HS256"],
                                 options={"verify_signature": True})
        # print(f"\n####\n{decoded_jwt = }\n####\n")
        role = decoded_jwt.get('role', [])
        return any(x in role for x in settings.KEYCLOAK_REQUIRED_ROLES)
    except jwt.exceptions.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Token unauthorized. {e}")
    
async def verify_readwrite(request: Request, 
                           settings: Annotated[Settings, Depends(get_settings)], 
                           token: Optional[str] = Depends(get_optional_token)):
    if not token:
        raise HTTPException(status_code=401, detail=f"No token offered.")
    print(f"\n####\n{token = }\n####\n")
    try:
        decoded_jwt = jwt.decode(token, get_settings().JWT_SECRET_KEY, audience="ontodocker",
                                 algorithms=["HS256"],
                                 options={"verify_signature": True})
        # print(f"\n####\n{decoded_jwt = }\n####\n")
        role = decoded_jwt.get('role', [])
        return any(x in role for x in settings.KEYCLOAK_ADMIN_ROLES) or any(x in role for x in settings.KEYCLOAK_READWRITE_ROLES)
    except jwt.exceptions.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Token unauthorized. {e}")
    
async def verify_admin(request: Request, 
                       settings: Annotated[Settings, Depends(get_settings)], 
                       token: Optional[str] = Depends(get_optional_token)):
    if not token:
        raise HTTPException(status_code=401, detail=f"No token offered.")
    print(f"\n####\n{token = }\n####\n")
    try:
        decoded_jwt = jwt.decode(token, get_settings().JWT_SECRET_KEY, audience="ontodocker",
                                 algorithms=["HS256"],
                                 options={"verify_signature": True})
        # print(f"\n####\n{decoded_jwt = }\n####\n")

        email = decoded_jwt.get('email')
        role = decoded_jwt.get('role', [])

        if settings.ADMIN_EMAIL and email == settings.ADMIN_EMAIL:
            return True
        return any(x in role for x in settings.KEYCLOAK_ADMIN_ROLES)
    except jwt.exceptions.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Token unauthorized. {e}")


async def check_auth_or_free_access(request: Request):
    if not request.session.get("name") and not request.url.path.startswith("/static") and not allow_unauthorized_readonly_ui_access:
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

async def check_auth(request: Request):
    if not request.session.get("name") and not (request.url.path.startswith("/static") and allow_unauthorized_readonly_ui_access):
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

async def maintainer_or_admin_role(request: Request, settings: Annotated[Settings, Depends(get_settings)], role=Depends(get_user_role)):
    role_list = settings.KEYCLOAK_ADMIN_ROLES+settings.KEYCLOAK_READWRITE_ROLES
    if role is None or not any(x in role for x in role_list):
        if request.method == "GET":
            raise HTTPException(status_code=403, detail="Access forbidden (admin or maintainer only)")
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
                  message="Access forbidden (admin or maintainer only)",
                  category="warning")
            raise HTTPException(
                status_code=status.HTTP_303_SEE_OTHER,  # redirect a POST request to a GET resource
                headers={'Location': redirect_url})
    return True

async def admin_role(request: Request, settings: Annotated[Settings, Depends(get_settings)], role=Depends(get_user_role)):
    if role is None or not any(x in role for x in settings.KEYCLOAK_ADMIN_ROLES):
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


def get_db_session():
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