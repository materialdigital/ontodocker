from typing import Annotated, Optional

from fastapi import Depends, APIRouter, status
from fastapi.requests import Request
from fastapi.responses import RedirectResponse, Response
from sqlmodel import Session
import httpx
from __init__ import templates
from urllib.parse import quote
import sys, os
from oauth import SSOAuth
import time
import bcrypt
from utils import flash
from triplestore.jena import get_jenaconn, FusekiConnection

sys.path.append("..")  # Adds higher directory to python modules path.
from config import get_settings, Settings
from db import User, get_user_by_sso_provider_and_user_identifier, get_user_by_user_identifier, get_sso_provider_by_id, get_enabled_sso_providers
from dependencies import get_db_session, get_client

# Note: when using from ..config import moduleA, I got ImportError: attempted relative import beyond top-level package
# so the hack here is to use sys.path.append("..")

router = APIRouter()

# Must not be initialized here, because it will be initialized in the first request
ssoAuth = None

async def fill_session_data(request, user, provider, db_session):
    request.session["id"] = user.id
    request.session["name"] = user.name
    request.session["role"] = user.role
    request.session["user_identifier"] = user.user_identifier
    request.session["api_key"] = user.api_key
    request.session["provider"] = provider
    user.last_login_timestamp = int(time.time())
    db_session.commit()
    db_session.refresh(user)

@router.get("/login",
            description="Login via username/password in Homepage.<br>"
                        "Note: You cannot try it in the document, but only via the "
                        "<a href='/'>Homepage</a>.",
            summary="Login",
            include_in_schema=False  # hide this endpoint in Swagger UI (http://localhost/docs)
)
async def login(request: Request,
                settings: Annotated[Settings, Depends(get_settings)], 
                db_session: Session = Depends(get_db_session),
                client: httpx.AsyncClient = Depends(get_client)):

    tdb_ids_jena = None
    try:
        tdb_ids_jena = await FusekiConnection.get_all_tdb_ids(client)
    except Exception as e:
        print(f"\n####\nFuseki:\nERROR: {str(e)}\n####\n")

    name = request.session.get("name", "anonymous")
    role = request.session.get("role", settings.OIDC_ADMIN_ROLE if os.getenv("ANONYMOUS_IS_ADMIN", "false") == "true" else None)

    host = request.headers.get("X-Forwarded-Host", request.url.hostname)
    port = request.headers.get("X-Forwarded-Port", request.url.port)
    scheme = request.headers.get("X-Forwarded-Proto", request.url.scheme)

    ownurl = f"{scheme}://{host}"
    if port and port != 443 and port != 80:
        ownurl = f"{scheme}://{host}:{port}"
    available_providers = get_enabled_sso_providers(db_session)
    return templates.TemplateResponse("login.html", {"request": request,
                                                     "has_vowl": False,
                                                     "tdb_id": "",
                                                     "tdb_name": "jena",
                                                     "tdb_ids_jena": tdb_ids_jena,
                                                     "name": name,
                                                     "ownurl": ownurl,
                                                     "property_tree": {},
                                                     "role": role,
                                                     "user_identifier": request.session.get("user_identifier", ""),
                                                     "provider": request.session.get("provider", ""),
                                                     "isAdminRole": role == settings.OIDC_ADMIN_ROLE,
                                                     "isReadWriteRole": role == settings.OIDC_READWRITE_ROLE,
                                                     "isReadOnlyRole": not role or role == settings.OIDC_READONLY_ROLE,
                                                     "available_providers": available_providers,
                                                     })

@router.post("/login")
async def login_post(request: Request, db_session: Session = Depends(get_db_session)):
    available_providers = get_enabled_sso_providers(db_session)
    
    form = await request.form()
    user_identifier = form.get("user_identifier")
    password = form.get("password")
    user = get_user_by_user_identifier(user_identifier, db_session)
    if not user:
        flash(request,
                  message="Benutzername oder Passwort falsch",
                  category="danger")
        return templates.TemplateResponse("login.html", {"request": request, "available_providers": available_providers}, status_code=403)
    if not bcrypt.checkpw(password.encode("utf-8"), user.password.encode("utf-8")):
        flash(request,
                  message="Benutzername oder Passwort falsch",
                  category="danger")
        return templates.TemplateResponse("login.html", {"request": request, "available_providers": available_providers}, status_code=403)
    await fill_session_data(request, user, "Local", db_session)
    return RedirectResponse(url='/', status_code=status.HTTP_303_SEE_OTHER)

@router.get("/login/{providerId}",
            description="Login via username/password in Homepage.<br>"
                        "Note: You cannot try it in the document, but only via the "
                        "<a href='/'>Homepage</a>.",
            summary="Login",
            include_in_schema=False  # hide this endpoint in Swagger UI (http://localhost/docs)
            )
async def login_sso(request: Request, db_session: Session = Depends(get_db_session)):
    providerId = request.path_params["providerId"]
    sso_provider = get_sso_provider_by_id(providerId, db_session)
    if not sso_provider or not sso_provider.enabled:
        return templates.TemplateResponse("403-visitor.html", {"request": request}, status_code=403)

    global ssoAuth
    if not ssoAuth:
        ssoAuth = SSOAuth()
    if providerId not in ssoAuth.get_registered_providers():
        if(sso_provider.type == "keycloak" or sso_provider.type == "orcid"):
            ssoAuth.register_oidc_provider(sso_provider)

    request.session.clear()
    redirect_uri = f'{request.url.scheme}://{request.url.netloc}/auth/{sso_provider.id}'
    return await ssoAuth.get_oauth_client(ssoAuth.generate_provider_name(sso_provider)).authorize_redirect(request, redirect_uri)

@router.get("/auth/{providerId}")
async def auth_keycloak(request: Request, db_session: Session = Depends(get_db_session)):
    providerId = request.path_params["providerId"]
    sso_provider = get_sso_provider_by_id(providerId, db_session)
    global ssoAuth
    if not ssoAuth:
        ssoAuth = SSOAuth()
    if not sso_provider or not sso_provider.enabled:
        return templates.TemplateResponse("403-visitor.html", {"request": request}, status_code=403)
    try:
        token = await ssoAuth.authorize_and_get_oauth_token(request)
    except Exception as e:
        print("Error:", e)
        return RedirectResponse('/')
    
    if token:
        if sso_provider.type == "keycloak":
            userinfo = token.get("userinfo")
            user = get_user_by_sso_provider_and_user_identifier(sso_provider.id, userinfo.preferred_username, db_session)
            if not user:
                user = get_user_by_sso_provider_and_user_identifier(sso_provider.id, userinfo.email, db_session)
                if not user:
                    if sso_provider.new_user_role and sso_provider.new_user_role != "":
                        username = userinfo.preferred_username if userinfo.preferred_username else userinfo.email
                        user = User(
                            name=userinfo.name if userinfo.name else username, 
                            user_identifier=username, 
                            role=sso_provider.new_user_role, 
                            sso_provider_id=sso_provider.id
                        )
                        db_session.add(user)
                        db_session.commit()
                    else:
                        return templates.TemplateResponse("403-visitor.html", {"request": request}, status_code=403)
            await fill_session_data(request, user, "keycloak", db_session)
        elif sso_provider.type == "orcid":
            userinfo = token.get("userinfo")
            user = get_user_by_sso_provider_and_user_identifier(sso_provider.id, userinfo.sub, db_session)
            if not user:
                if sso_provider.new_user_role and sso_provider.new_user_role != "":
                    username = userinfo.sub
                    user = User(
                        name=userinfo.given_name if userinfo.given_name else username, 
                        user_identifier=username, 
                        role=sso_provider.new_user_role,
                        sso_provider_id=sso_provider.id
                    )
                    db_session.add(user)
                    db_session.commit()
                else:
                    return templates.TemplateResponse("403-visitor.html", {"request": request}, status_code=403)
            await fill_session_data(request, user, "orcid", db_session)
    return RedirectResponse('/')

@router.get("/login/orcid",
            description="Login via username/password in Homepage.<br>"
                        "Note: You cannot try it in the document, but only via the "
                        "<a href='/'>Homepage</a>.",
            summary="Login",
            include_in_schema=False  # hide this endpoint in Swagger UI (http://localhost/docs)
            )
async def login_orcid(request: Request):
    global ssoAuth
    if not ssoAuth:
        ssoAuth = SSOAuth()
    redirect_uri = f'{request.url.scheme}://{request.url.netloc}/auth/orcid'
    return await ssoAuth.get_oauth_client("orcid").authorize_redirect(request, redirect_uri)

@router.get("/auth/orcid")
async def auth_orcid(request: Request, db_session: Session = Depends(get_db_session)):
    global ssoAuth
    if not ssoAuth:
        ssoAuth = SSOAuth()
    token = await ssoAuth.authorize_and_get_oauth_token(request)
    userinfo = token.get("userinfo")
    sso_provider_id = -1
    user =  get_user_by_sso_provider_and_user_identifier(sso_provider_id, userinfo.sub, db_session)
    if not user:
        return templates.TemplateResponse("403-visitor.html", {"request": request}, status_code=403)
    await fill_session_data(request, user, "orcid", db_session)
    return RedirectResponse('/')

@router.get("/logout",
            description="Logout.<br>"
                        "Note: You cannot try it in the document, but only via the <a href='/'>Website</a>.",
            summary="Logout",
            include_in_schema=False  # hide this endpoint in Swagger UI (http://localhost/docs)
            )
def logout_new(request: Request, response: Response) -> RedirectResponse:

    global ssoAuth
    if not ssoAuth:
        ssoAuth = SSOAuth()
    redirect_url = ssoAuth.get_logout_url(request)

    # Clear session
    request.session.clear()
    
    return RedirectResponse(redirect_url)