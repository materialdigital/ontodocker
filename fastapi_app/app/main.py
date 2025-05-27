import asyncio
import os
import time
from json import JSONDecodeError
import httpx
from typing import Annotated
from config import get_settings, Settings
from typing import Optional
import datetime
import zoneinfo
import bcrypt
import re
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, status, Form, Query, UploadFile, File
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.requests import Request
from fastapi.responses import RedirectResponse
from fastapi.responses import Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware
from sqlmodel import Session
from db import User, SSOProvider, get_user_by_sso_provider_and_user_identifier, get_user_by_id, get_all_users_order_by_name, SparqlQuery, find_all_sparql_query, find_sparql_query_by_user_id_or_public, find_sparql_query_by_id, find_sparql_query_by_user, get_sso_provider_by_name, get_sso_provider_by_id, get_users_by_sso_provider_id, get_all_sso_providers, get_db_version_or_init, get_application_store_by_key, create_or_update_application_store_by, find_ckan_dataset_by_dataset_name, CkanDataset

from werkzeug.utils import secure_filename

# I can't use from . import XXX (ImportError: attempted relative import with no known parent package)
from __init__ import create_db_and_tables
from __init__ import templates


from utils import flash, extract_queryresults, is_file_allowed
from triplestore.jena import get_jenaconn, FusekiConnection
from routers import auth, api
from doc import description
import secrets
import hashlib

from dependencies import get_client, check_auth, check_auth_or_free_access, get_user_role, admin_role, maintainer_or_admin_role, decode_token, get_db_session, create_apikey

from cachetools import TTLCache
import json
from fastapi.responses import FileResponse
import urllib
import urllib.request as urllib2

cache = TTLCache(maxsize=500, ttl=1)

app = FastAPI(title="Ontodocker App", version="1.0.0", description=description)

session_time_days = int(os.environ.get("MAX_SESSION_TIME_IN_DAYS", 14))

# max_age is by default set to 14 days, this should be less than the "SSO
# Session Idle" time of the OIDC provider settings. so that if the session expires after the desired time, the user will
# be redirected to the login page
app.add_middleware(GZipMiddleware)  # Defaults to 500 bytes

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, tags=["Authentication"])
app.include_router(api.router,
                   prefix="/api/v1")


# see: https://github.com/tiangolo/fastapi/discussions/7900#discussioncomment-5145102
class AuthStaticFiles(StaticFiles):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

    async def __call__(self, scope, receive, send) -> None:
        assert scope["type"] == "http"

        request = Request(scope, receive)
        allowed_extensions = {".ico", ".css", ".svg", ".ttf", ".woff2"}  # css, svg, or fontawesome webfonts files
        if self.is_allowed_file(request.url.path, allowed_extensions):
            await super().__call__(scope, receive, send)
        else:
            await check_auth(request)
            await super().__call__(scope, receive, send)

    def is_allowed_file(self, path: str, allowed_extensions: set) -> bool:
        # Check if the requested path ends with one of the allowed extensions
        return any(path.lower().endswith(extension) for extension in allowed_extensions)


app.mount("/static", AuthStaticFiles(directory="static"), name="static")
#idee app.mount("/static", StaticFiles(directory="static"), name="static") # /wo oauth. also remove als check_aouth dependencies
# auch get("name") raus

@app.on_event("startup")
async def on_startup():
    create_db_and_tables()
    migrate_db()

    # remove default dataset "ds" in Fuseki
    async with httpx.AsyncClient() as client:
        try:
            tdb_ids_jena = await FusekiConnection.get_all_tdb_ids(client)
            if "ds" in tdb_ids_jena:
                await get_jenaconn("ds").destroy_ds(client)
        except Exception as e:
            print(f"Error while removing default dataset 'ds' in Fuseki:\n{str(e)}")

def migrate_db():
    version = get_db_version_or_init(next(get_db_session()))
    if version < 1:
        print("Migrating database to version 1")
        # Add new_user_role column to SSOProvider table
        session = next(get_db_session())
        result = session.execute("select count(*) from pragma_table_info('ssoprovider') where name='new_user_role';")
        if result.scalar() == 0:
            session.execute("ALTER TABLE ssoprovider ADD COLUMN new_user_role TEXT")
        session.execute("UPDATE applicationstore SET value = '1' WHERE key = 'db_version'")
        session.commit()
        session.close()
        version = 1
        print("Database migrated to version 1")

@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    # print(f"{process_time = }")
    response.headers["X-Process-Time"] = f"{round(process_time, 3)} s"
    return response


# Adding a middleware returning a 504 error if the request processing time is above a certain threshold
@app.middleware("http")
async def timeout_middleware(request: Request, call_next):
    timeout = 600  # 60s
    try:
        return await asyncio.wait_for(call_next(request), timeout=timeout)

    except asyncio.TimeoutError:
        return JSONResponse(content=f'Request processing time exceeded limit ({timeout})',
                            status_code=status.HTTP_504_GATEWAY_TIMEOUT)
    
@app.middleware("http")
async def refresh_user(request: Request, call_next):
    if request.url.path != "/logout":
        user_id = request.session.get("id")
        if user_id:
            user = get_user_by_id(user_id, next(get_db_session()))
            if user:
                request.session["role"] = user.role
            else:
                return RedirectResponse(url="/logout", status_code=status.HTTP_303_SEE_OTHER)
                
    return await call_next(request)


app.add_middleware(SessionMiddleware, max_age=session_time_days * 24 * 60 * 60,
                   secret_key=hashlib.sha256(os.environ.get("JWT_SECRET_KEY", secrets.token_urlsafe(32)).encode()).hexdigest()) 

@app.get("/",
         description="Homepage.<br>"
                     "Visit <a href='/'>Homepage</a>.",
         summary="Homepage",
         tags=["Homepage"],
         dependencies=[Depends(check_auth_or_free_access)],
         include_in_schema=False  # hide this endpoint in Swagger UI (http://localhost/docs)
         )
async def homepage(response: Response, request: Request, 
                   settings: Annotated[Settings, Depends(get_settings)],
                   client: httpx.AsyncClient = Depends(get_client)):
    # Refresh user info in session
    # await refresh_user_session(request)


    # check Fuseki triplestore for datasets
    tdb_ids_jena = None
    try:
        tdb_ids_jena = await FusekiConnection.get_all_tdb_ids(client)
    except Exception as e:
        print(f"\n####\nFuseki:\nERROR: {str(e)}\n####\n")

    # set variables for navbar
    name = request.session.get("name", "anonymous")
    api_key = request.session.get("api_key", "")
    role = request.session.get("role", settings.OIDC_ADMIN_ROLE if os.getenv("ANONYMOUS_IS_ADMIN", "false") == "true" else None)

    host = request.headers.get("X-Forwarded-Host", request.url.hostname)
    port = request.headers.get("X-Forwarded-Port", request.url.port)
    scheme = request.headers.get("X-Forwarded-Proto", request.url.scheme)

    ownurl = f"{scheme}://{host}"
    if port and port != 443 and port != 80:
        ownurl = f"{scheme}://{host}:{port}"
        

    if tdb_ids_jena and not role == settings.OIDC_ADMIN_ROLE:
        tdb_ids_jena = [item for item in tdb_ids_jena if
                        "-mem" not in item and
                        "_mem" not in item
                        ]

    return templates.TemplateResponse("index.html", {"request": request,
                                                     "has_vowl": False,
                                                     "tdb_id": "",
                                                     "tdb_name": "jena",
                                                     "tdb_ids_jena": tdb_ids_jena,
                                                     "name": name,
                                                     "api_key": api_key if api_key else "",
                                                     "api_key_default_valid_days": settings.JWT_DEFAULT_DAYS_VALID,
                                                     "api_key_valid_to": decode_token(api_key).get("exp") if api_key else "-",
                                                     "ownurl": ownurl,
                                                     "property_tree": {},
                                                     "role": role,
                                                     "user_identifier": request.session.get("user_identifier", ""),
                                                     "provider": request.session.get("provider", ""),
                                                     "isAdminRole": role == settings.OIDC_ADMIN_ROLE,
                                                     "isReadWriteRole": role == settings.OIDC_READWRITE_ROLE,
                                                     "isReadOnlyRole": not role or role == settings.OIDC_READONLY_ROLE,
                                                     })

@app.get("/refresh_api_key",
         dependencies=[Depends(check_auth)],
         include_in_schema=False  # hide this endpoint in Swagger UI (http://localhost/docs)
         )
async def generate_api_key(request: Request, 
                           settings: Annotated[Settings, Depends(get_settings)],
                           db_session: Session = Depends(get_db_session)
    ):

    valid = request.query_params.get("valid")

    userid = request.session["id"]

    minDaysValid = int(os.environ.get("JWT_MIN_DAYS_VALID", 1))
    maxDaysValid = int(os.environ.get("JWT_MAX_DAYS_VALID", 90))
    if valid and valid.isdigit() and int(valid) >= minDaysValid and int(valid) <= maxDaysValid:
        # get user by query
        user = get_user_by_id(userid, db_session)
        
        api_key = create_apikey(user.id, int(valid), request, settings)
        user.api_key = api_key
        db_session.commit()
        db_session.refresh(user)
        print("Updated user:", user)

        returnObj = {
            "apiKey": api_key,
            "validTo": decode_token(api_key).get("exp")
        }
        request.session["api_key"] = api_key;
        return JSONResponse(content=returnObj, status_code=200)
    else:
        return JSONResponse(content=f"Invalid valid days. Must be between {minDaysValid} days and {maxDaysValid} days.", status_code=400)

@app.post('/update_password',
          description="Update password of current user",
          dependencies=[Depends(check_auth)],
          include_in_schema=False)
async def update_password(request: Request,
                        settings: Annotated[Settings, Depends(get_settings)],
                        db_session: Session = Depends(get_db_session)):
        try:
            data = await request.json()
            # Check if old password is correct
            old_password = data.get("old_password", None)
            if not old_password:
                return JSONResponse(content=f"Old password must be given!", status_code=400)
            user_id = request.session.get("id")
            result = get_user_by_id(user_id, db_session)
            if result:
                if result.sso_provider_id is not None:
                    return JSONResponse(content=f"Cannot change password of SSO user!", status_code=400)
                if not bcrypt.checkpw(old_password.encode("utf-8"), result.password.encode("utf-8")):
                    return JSONResponse(content=f"Old password is incorrect!", status_code=400)
            else:
                return JSONResponse(content=f"User with ID {user_id} does not exist!", status_code=404)
            
            new_password1 = data.get("new_password1", None)
            new_password2 = data.get("new_password2", None)
            if not new_password1 or len(new_password1) < 8:
                return JSONResponse(content=f"Password must be at least 8 characters long!", status_code=400)
            if new_password1 != new_password2:
                return JSONResponse(content=f"Passwords do not match!", status_code=400)
            if result:
                hashed_password = bcrypt.hashpw(new_password1.encode("utf-8"), bcrypt.gensalt())
                result.password = hashed_password.decode("utf-8")
                db_session.commit()
                db_session.refresh(result)
                return JSONResponse(content="Password changed!", status_code=200)
            else:
                return JSONResponse(content=f"User with ID {user_id} does not exist!", status_code=404)
        except Exception as e:
            print(f"Unexpected error: {e}")
            return JSONResponse(content=str(e), status_code=400)

# This post request will reload the page
@app.post("/create_dataset",
          description="Create a new dataset in the Fuseki Jena triplestore. This endpoint requires authentication and the user must have the maintainer or admin role. The dataset is created by calling the `create_ds` method of the `FusekiConnection` class. If the dataset is successfully created, a success flash message is displayed. Otherwise, a warning flash message is displayed with the error message. After creating the dataset, the user is redirected to the homepage. If the `tdb_id` parameter is provided, the user is redirected to the corresponding dataset page. Otherwise, the user is redirected to the homepage.",
          summary="Create new dataset",
          tags=["Dataset"],
          dependencies=[Depends(check_auth_or_free_access), Depends(maintainer_or_admin_role)],
          include_in_schema=False  # hide this endpoint in Swagger UI (http://localhost/docs)
          )
async def create_dataset(response: Response, request: Request, create_tdb_id: Annotated[str, Form()],
                         settings: Annotated[Settings, Depends(get_settings)],
                         client: httpx.AsyncClient = Depends(get_client),
                         ):
    redirect_url = request.headers.get('Referer')  # get the url before redirection

    host = request.headers.get("X-Forwarded-Host", request.url.hostname)
    port = request.headers.get("X-Forwarded-Port", request.url.port)
    scheme = request.headers.get("X-Forwarded-Proto", request.url.scheme)

    ownurl = f"{scheme}://{host}"
    if port and port != 443 and port != 80:
        ownurl = f"{scheme}://{host}:{port}"

    # check Fuseki triplestore for datasets
    tdb_ids_jena = None
    try:
        tdb_ids_jena = await FusekiConnection.get_all_tdb_ids(client)
        if tdb_ids_jena is None:
            raise Exception("TriplestoreNotAvailable")

        # Dataset names containing "/" are ignored by Fuseki
        create_tdb_id = create_tdb_id.replace("/", "")
        create_tdb_id = create_tdb_id.replace(" ", "_")


        print(f"\n####\nTry to create a new dataset called: {create_tdb_id}\n####\n")
        if create_tdb_id in tdb_ids_jena:
            raise Exception("DatasetNameNotAllowed")
        r = await get_jenaconn(create_tdb_id).create_ds(client)
        tdb_name = "jena"  # set in order to get back to dataset page
        tdb_id = create_tdb_id
        if r.status_code == 200:
            flash(request,
                  message=f"Dataset name <strong>{tdb_id}</strong> created",
                  category="success")
            redirect_url = f"{ownurl}/{tdb_name}/{tdb_id}"
        else:
            flash(request,
                  message=r.content.decode("utf-8"),
                  category="danger")

    except Exception as e:
        print(f"\n####\nFuseki:\nERROR\n####\n")

        if "TriplestoreNotAvailable" in str(e):
            flash(request,
                  message="Triplestore unavailable. Please try again later.",
                  category="danger")
        elif "DatasetNameNotAllowed" in str(e):
            flash(request,
                  message="Dataset name already exist. Please choose something else.",
                  category="warning")
        else:
            flash(request,
                  message=f"Unexpected error: {e}",
                  category="danger")

    return RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)

@app.get('/jena/{tdb_id}/generate_vowl',
         description="Generate VOWL visualization of a dataset in the Fuseki Jena triplestore. This endpoint requires authentication and the user must have the maintainer or admin role. The VOWL visualization is generated by calling the `get_vowl` method of the `JenaConnection` class. If the VOWL visualization is successfully generated, a success flash message is displayed. Otherwise, a warning flash message is displayed with the error message. After generating the VOWL visualization, the user is redirected to the dataset page.",
         summary="Generate VOWL visualization",
         tags=["Datasets"],
         dependencies=[Depends(check_auth_or_free_access)],
         include_in_schema=False  # hide this endpoint in Swagger UI (http://localhost/docs)
         )
async def generate_vowl(response: Response, request: Request, tdb_id: str = "",
                        client: httpx.AsyncClient = Depends(get_client)):
    r = await get_jenaconn(tdb_id).get_vowl(client)
    return JSONResponse(content="", status_code=200)

@app.get('/jena/{tdb_id}',
         description="Query UI page for a specific dataset in the Fuseki Jena triplestore. This page allows users to query the data in the dataset using SPARQL queries. The dataset is identified by the `tdb_id` path parameter. If the dataset does not exist or the user does not have access to it, a 404 error is returned. The page displays the dataset name, available datasets in the triplestore, user information, and options based on the user's role. The page also shows whether the dataset is empty or not. If the dataset is not empty, a sample SPARQL query is executed to retrieve the first two triples in the dataset. The page also provides a visualization of the dataset using VOWL. The template used for rendering the page is 'index.html'.",
         summary="Query UI page",
         tags=["Datasets"],
         dependencies=[Depends(check_auth_or_free_access)],
         include_in_schema=False  # hide this endpoint in Swagger UI (http://localhost/docs)
         )
async def datasets(response: Response, request: Request, settings: Annotated[Settings, Depends(get_settings)],
                   tdb_id: str = "", tdb_name: str = "jena",
                   client: httpx.AsyncClient = Depends(get_client)):
    tdb_ids_jena = []
    tdb_ids_jena = await FusekiConnection.get_all_tdb_ids(client)
    print(f"\n####\nFuseki:\n{tdb_ids_jena = }\n####\n")
    if tdb_ids_jena is None:
        raise HTTPException(status_code=503, detail="Triplestore unavailable")

    # set variables for navbar
    name = request.session.get("name", "anonymous")
    api_key = request.session.get("api_key", "")
    role = request.session.get("role", settings.OIDC_ADMIN_ROLE if os.getenv("ANONYMOUS_IS_ADMIN", "false") == "true" else None)

    host = request.headers.get("X-Forwarded-Host", request.url.hostname)
    port = request.headers.get("X-Forwarded-Port", request.url.port)
    scheme = request.headers.get("X-Forwarded-Proto", request.url.scheme)

    ownurl = f"{scheme}://{host}"
    if port and port != 443 and port != 80:
        ownurl = f"{scheme}://{host}:{port}"

    if tdb_ids_jena and not role == settings.OIDC_ADMIN_ROLE:
        tdb_ids_jena = [item for item in tdb_ids_jena if
                        "-mem" not in item and
                        "_mem" not in item
                        ]

    if tdb_name == "jena":
        if tdb_id not in tdb_ids_jena:
            raise HTTPException(status_code=404, detail="dataset name not found")
    else:
        raise HTTPException(status_code=404, detail="Triplestore not exist")

    ds_isempty = True
    #if tdb_name == "jena":
    query ="SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 2"
    
    r = await get_jenaconn(tdb_id).query(query, client)
    head, data, raw = extract_queryresults(r)
    
    if data:
        ds_isempty = False

    graphs = await get_jenaconn(tdb_id).get_namedgraphs(client)
    # head, graphs, raw = extract_queryresults(r_namedgraph)
    named_graphs = []
    if graphs:
        named_graphs = [{"iri": x} for x in graphs]

    return templates.TemplateResponse("index.html", {"request": request,
                                                     "ds_isempty": ds_isempty,
                                                     "tdb_id": tdb_id,
                                                     "tdb_name": tdb_name,
                                                     "tdb_ids_jena": tdb_ids_jena,
                                                     "name": name,
                                                     "api_key": api_key if api_key else "",
                                                     "api_key_default_valid_days": settings.JWT_DEFAULT_DAYS_VALID,
                                                     "api_key_valid_to": decode_token(api_key).get("exp") if api_key else "-",
                                                     "ownurl": ownurl,
                                                     "role": role,
                                                     "user_identifier": request.session.get("user_identifier", ""),
                                                     "provider": request.session.get("provider", ""),
                                                     "named_graphs": named_graphs,
                                                     "isAdminRole": role == settings.OIDC_ADMIN_ROLE,
                                                     "isReadWriteRole": role == settings.OIDC_READWRITE_ROLE,
                                                     "isReadOnlyRole": not role or role == settings.OIDC_READONLY_ROLE
                                                     })

@app.get("/jena/{tdb_id}/reasoner",
            description="Get the reasoner of a dataset in the Fuseki Jena triplestore. This endpoint requires authentication and the user must have the maintainer or admin role.",
            summary="Get reasoner",
            tags=["Datasets"],
            dependencies=[Depends(check_auth_or_free_access)],
            include_in_schema=False  # hide this endpoint in Swagger UI (http://localhost/docs)
            )
async def get_reasoner(response: Response, request: Request, tdb_id: str = ""):
     r = await get_jenaconn(tdb_id).get_reasoner(tdb_id)
     return r

@app.post("/jena/{tdb_id}/reasoner",
          description="Set a reasoner on a dataset in the Fuseki Jena triplestore. This endpoint requires authentication and the user must have the maintainer or admin role. ",
          summary="Set reasoner",
          tags=["Datasets"],
          dependencies=[Depends(check_auth_or_free_access), Depends(maintainer_or_admin_role)],
          include_in_schema=False  # hide this endpoint in Swagger UI (http://localhost/docs)
          )
async def set_reasoner(response: Response, request: Request, tdb_id: str = ""):
    data = await request.json()
    reasoner = data.get("reasoner", None)

    r = await get_jenaconn(tdb_id).set_reasoner(tdb_id, reasoner)
    return r
        

@app.get("/jena/{tdb_id}/ckan",
         description="Check if dataset exists in CKAN.",
         summary="Check if dataset exists in CKAN",
         dependencies=[Depends(check_auth_or_free_access)],
         include_in_schema=False)
async def get_ckan_dataset(request: Request,
                             tdb_id: str,
                             client: httpx.AsyncClient = Depends(get_client),
                             db_session: Session = Depends(get_db_session)):
    # Get CKAN dataset by ID
    ckan_url = get_application_store_by_key(db_session, "ckan_url")
    ckan_api_key = get_application_store_by_key(db_session, "ckan_api_key")
    ckan_api_format = get_application_store_by_key(db_session, "ckan_api_format", "default")
    if ckan_url and ckan_api_key:
        try:
            ckan_dataset = find_ckan_dataset_by_dataset_name(tdb_id, db_session)
            if ckan_dataset:
                ckan_url = ckan_url + "/api/3/action/package_show"
                headers = {
                    "Authorization": ckan_api_key,
                    "Content-Type": "application/json"
                }
                data = {
                    "id": ckan_dataset.ckan_id
                }
                r = await client.post(ckan_url, headers=headers, json=data)
                result_json = r.json()
                if r.status_code == 200 and "success" in result_json and result_json["success"]:
                    resultJson = result_json["result"]
                    if ckan_api_format == "dcat":
                        resultJson["author"] = resultJson.get("publisher", [{}])[0].get("name", "")
                        resultJson["author_email"] = resultJson.get("publisher", [{}])[0].get("email", "")
                    return JSONResponse(content=resultJson, status_code=200)
                else:
                    return JSONResponse(content={"exists": False}, status_code=200)
            else:
                return JSONResponse(content="", status_code=404)
        except Exception as e:
            print(f"Unexpected error: {e}")
            return JSONResponse(content=str(e), status_code=400)
    else:
        return JSONResponse(content=str("CKAN URL or API key not configured"), status_code=424)
    
@app.post('/jena/{tdb_id}/ckan',
          description="Create or update dataset in CKAN.",
          summary="Create or update dataset in CKAN",
          dependencies=[Depends(check_auth)],
          include_in_schema=False)
async def create_or_update_ckan_dataset(request: Request,
                              tdb_id: str,
                              client: httpx.AsyncClient = Depends(get_client),
                              db_session: Session = Depends(get_db_session)):
    
    host = request.headers.get("X-Forwarded-Host", request.url.hostname)
    port = request.headers.get("X-Forwarded-Port", request.url.port)
    scheme = request.headers.get("X-Forwarded-Proto", request.url.scheme)

    ownurl = f"{scheme}://{host}"
    if port and port != 443 and port != 80:
        ownurl = f"{scheme}://{host}:{port}"

    data = await request.json()
    dataset_name = data.get("dataset_name", None)
    # regex the name of the new dataset, must be between 2 and 100 characters long and contain only lowercase alphanumeric characters, - and _
    if not dataset_name or not re.match(r"^[a-z0-9_-]{2,100}$", dataset_name):
        return JSONResponse(content="Invalid dataset name. Must be between 2 and 100 characters long and contain only lowercase alphanumeric characters, - and _", status_code=400)

    ckan_publisher_name = data.get("ckan_publisher_name", request.session.get("name", ""))
    ckan_publisher_email = data.get("ckan_publisher_email", "")

    try:
        ckan_url = get_application_store_by_key(db_session, "ckan_url")
        ckan_api_key = get_application_store_by_key(db_session, "ckan_api_key")
        ckan_organization_id = get_application_store_by_key(db_session, "ckan_organization_id")
        ckan_group_ids = json.loads(get_application_store_by_key(db_session, "ckan_group_ids", "[]"))
        ckan_api_format = get_application_store_by_key(db_session, "ckan_api_format", "default")
        if ckan_url and ckan_api_key and ckan_organization_id:
            headers = {
                "Authorization": ckan_api_key,
                "Content-Type": "application/json"
            }
            ckan_dataset = find_ckan_dataset_by_dataset_name(tdb_id, db_session)
            if not ckan_dataset:
                ckan_dataset = CkanDataset(dataset_name=tdb_id, user_id=request.session.get("id"), published_timestamp=int(time.time()))
                ckan_url = ckan_url + "/api/3/action/package_create"
                postData = {
                    "name": dataset_name,
                    "title": dataset_name,
                    "private": False,
                    "notes": data.get("dataset_description"),
                    "owner_org": ckan_organization_id,
                    "author": ckan_publisher_name,
                    "author_email": ckan_publisher_email,
                    "groups": [{"id": group_id} for group_id in ckan_group_ids],
                    "resources": [
                        {
                            "name": f"Exploreable dataset with YasGUI at {ownurl}",
                            "url": f"{ownurl}/jena/{tdb_id}",
                            "description": "Points to the user interface",
                            "mimetype": "text/html"
                        },
                        {
                            "name": f"SPARQL API endpoint",
                            "url": f"{ownurl}/api/v1/jena/{tdb_id}/sparql",
                            "mimetype": "application/sparql-results+xml",
                            "format": "sparql"
                        },
                        {
                            "name": f"Data API endpoint",
                            "url": f"{ownurl}/api/v1/jena/{tdb_id}",
                            "mimetype": "text/turtle"
                        }
                    ],
                    "tags": [{"name": tag} for tag in data.get("dataset_tags", [])]
                } 
                if ckan_api_format == "dcat":
                    postData = {
                        "name": dataset_name,
                        "title": dataset_name,
                        "private": False,
                        "notes": data.get("dataset_description"),
                        "owner_org": ckan_organization_id,
                        "publisher": [{"name": ckan_publisher_name, "email": ckan_publisher_email}],
                        "groups": [{"id": group_id} for group_id in ckan_group_ids],
                        "resources": [
                            {
                                "name": f"Exploreable dataset with YasGUI at {ownurl}",
                                "url": f"{ownurl}/jena/{tdb_id}",
                                "description": "Points to the user interface",
                                "mimetype": "text/html"
                            },
                            {
                                "name": f"SPARQL API endpoint",
                                "url": f"{ownurl}/api/v1/jena/{tdb_id}/sparql",
                                "mimetype": "application/sparql-results+xml",
                                "format": "sparql"
                            },
                            {
                                "name": f"Data API endpoint",
                                "url": f"{ownurl}/api/v1/jena/{tdb_id}",
                                "mimetype": "text/turtle"
                            }
                        ],
                        "tags": [{"name": tag} for tag in data.get("dataset_tags", [])]
                    }
                r = await client.post(ckan_url, headers=headers, json=postData)
                result_json = r.json()
            else:
                ckan_dataset.published_timestamp = int(time.time())
                ckan_dataset.user_id = request.session.get("id")
                ckan_url = ckan_url + "/api/3/action/package_patch"
                postData = {
                    "id": ckan_dataset.ckan_id,
                    "name": dataset_name,
                    "title": dataset_name,
                    "notes": data.get("dataset_description"),
                    "author": ckan_publisher_name,
                    "author_email": ckan_publisher_email,
                    "tags": [{"name": tag} for tag in data.get("dataset_tags", [])],
                    "groups": [{"id": group_id} for group_id in ckan_group_ids]
                }
                if ckan_api_format == "dcat":
                    postData = {
                        "id": ckan_dataset.ckan_id,
                        "name": dataset_name,
                        "title": dataset_name,
                        "notes": data.get("dataset_description"),
                        "publisher": [{"name": ckan_publisher_name, "email": ckan_publisher_email}],
                        "tags": [{"name": tag} for tag in data.get("dataset_tags", [])],
                        "groups": [{"id": group_id} for group_id in ckan_group_ids]
                    }
                r = await client.post(ckan_url, headers=headers, json=postData)
                result_json = r.json()
            if r.status_code == 200 and "success" in result_json and result_json["success"]:
                ckan_dataset.ckan_id = result_json["result"]["id"]
                if not ckan_dataset.id:
                    db_session.add(ckan_dataset)
                    db_session.commit()
                else:
                    db_session.commit()

                return JSONResponse(content="Linked Dataset in CKAN", status_code=200)
            else:
                if "error" in result_json:
                    error_message = ", ".join([f"{k}: {', '.join(v)}" for k, v in result_json["error"].items() if k != "__type"])
                    return JSONResponse(content=error_message, status_code=400)
                return JSONResponse(content=result_json, status_code=400)
        else:
            return JSONResponse(content=str("CKAN URL or API key or Organization not configured"), status_code=424)
    except Exception as e:
        print(f"Unexpected error: {e}")
        return JSONResponse(content=str(e), status_code=400)

@app.delete('/jena/{tdb_id}/ckan',
            description="Delete dataset in CKAN.",
            summary="Delete dataset in CKAN",
            dependencies=[Depends(check_auth)],
            include_in_schema=False)
async def delete_ckan_dataset(request: Request,
                              tdb_id: str,
                              client: httpx.AsyncClient = Depends(get_client),
                              db_session: Session = Depends(get_db_session)):
    try:
        ckan_url = get_application_store_by_key(db_session, "ckan_url")
        ckan_api_key = get_application_store_by_key(db_session, "ckan_api_key")
        if ckan_url and ckan_api_key:
            ckan_dataset = find_ckan_dataset_by_dataset_name(tdb_id, db_session)
            if ckan_dataset:
                ckan_url = ckan_url + "/api/3/action/package_delete"
                headers = {
                    "Authorization": ckan_api_key,
                    "Content-Type": "application/json"
                }
                data = {
                    "id": ckan_dataset.ckan_id
                }
                r = await client.post(ckan_url, headers=headers, json=data)
                if r.status_code == 200:
                    db_session.delete(ckan_dataset)
                    db_session.commit()
                    return JSONResponse(content="Unlinked Dataset in CKAN", status_code=200)
                else:
                    return JSONResponse(content=r.text, status_code=400)
            else:
                return JSONResponse(content="Dataset not found in CKAN", status_code=404)
        else:
            return JSONResponse(content=str("CKAN URL or API key not configured"), status_code=424)
    except Exception as e:
        print(f"Unexpected error: {e}")
        return JSONResponse(content=str(e), status_code=400)

# This post request will reload the page
# Other post requests like query, update, and upload
# are handled in the individual endpoints below with axios in frontend to prevent page reloads
@app.post('/destroy_dataset',
          description="This endpoint is used to destroy a dataset in the Fuseki Jena triplestore."
                      "It requires authentication and the user must have the maintainer or admin role."
                      "The dataset is destroyed by calling the `destroy_ds` method of the JenaConnection class."
                      "If the dataset is successfully destroyed, a success flash message is displayed."
                      "Otherwise, a warning flash message is displayed with the error message."
                      "After destroying the dataset, the user is redirected to the homepage."
                      "If the `tdb_name` and `tdb_id` parameters are provided, the user is redirected to the corresponding dataset page."
                      "Otherwise, the user is redirected to the homepage.",
          summary="Destroy dataset",
          tags=["Datasets"],
          dependencies=[Depends(check_auth_or_free_access), Depends(maintainer_or_admin_role)],
          include_in_schema=False  # hide this endpoint in Swagger UI (http://localhost/docs)
          )
async def destroy_dataset(response: Response, request: Request, tdb_id: Annotated[str, Form()], tdb_name: str = "jena",
                          client: httpx.AsyncClient = Depends(get_client),
                          db_session: Session = Depends(get_db_session)):
    try:
        r = await get_jenaconn(tdb_id).destroy_ds(client)
        print(f"\n\n##########\n{r.status_code = }\n{str(r.content.decode('utf-8')) = }\n##########\n\n")
        if r.status_code == 200:
            flash(request,
                  message=f"Dataset <strong>{tdb_id}</strong> deleted",
                  category="success")
            tdb_name = ""  # set to empty string in order to get back to homepage
        else:
            flash(request,
                  message=r.content.decode("utf-8"),
                  category="warning")

    except Exception as e:
        flash(request,
              message=f"Unexpected error: {e}",
              category="danger")

    if tdb_name and tdb_id:
        redirect_url = f"/{tdb_name}/{tdb_id}"
    else:
        redirect_url = "/"

    ckan_dataset = find_ckan_dataset_by_dataset_name(tdb_id, db_session)
    if ckan_dataset:
        # Delete dataset from CKAN
        try:
            ckan_url = get_application_store_by_key(db_session, "ckan_url")
            ckan_api_key = get_application_store_by_key(db_session, "ckan_api_key")
            if ckan_url and ckan_api_key:
                ckan_url = ckan_url + "/api/3/action/package_delete"
                headers = {
                    "Authorization": ckan_api_key,
                    "Content-Type": "application/json"
                }
                data = {
                    "id": ckan_dataset.ckan_id
                }
                r = await client.post(ckan_url, headers=headers, json=data)
                if r.status_code == 200:
                    flash(request,
                          message=f"Dataset <strong>{tdb_id}</strong> deleted from CKAN",
                          category="success")
                else:
                    flash(request,
                          message=f"Error while deleting dataset from CKAN: {r.text}",
                          category="danger")
            db_session.delete(ckan_dataset)
            db_session.commit()
        except Exception as e:
            flash(request,
                  message=f"Unexpected error: {e}",
                  category="danger")

    print(f"\n####\n{redirect_url = }\n####\n")
    return RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)


@app.get('/jena/{tdb_id}/clear_cache',
         description="Clear cache of query results",
         summary="Clear cache of query results",
         tags=["Datasets"],
         dependencies=[Depends(check_auth_or_free_access), Depends(maintainer_or_admin_role)],
         include_in_schema=False
         )
async def clear_cache(response: Response, request: Request, tdb_id: str = "", tdb_name: str = "jena"):
    try:
        # Clear the cache
        cache.clear()
        print(f"Dataset {tdb_id} cache cleared")
        flash(request,
              message=f"Dataset <strong>{tdb_id}</strong> cache cleared",
              category="success")
    except Exception as e:
        print(f"Unexpected error: {e} while clearing cache")
        flash(request,
              message=f"Unexpected error: {e} while clearing cache",
              category="danger")

    if tdb_name and tdb_id:
        redirect_url = f"/{tdb_name}/{tdb_id}"
    else:
        redirect_url = "/"
    return RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)

@app.get("/jena/{tdb_id}/download",
         description="Download Trig data of a dataset.",
         summary="Download Trig data of a dataset",
         dependencies=[Depends(check_auth_or_free_access)],
         include_in_schema=False)
async def download_dataset(request: Request,
                            tdb_id: str,
                            client: httpx.AsyncClient = Depends(get_client)):
     try:
          r = await get_jenaconn(tdb_id).data(client)
          if r.status_code == 200:
                current_timestamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
                return Response(content=r.content, media_type="application/trig", headers={"Content-Disposition": f"attachment; filename={tdb_id}_{current_timestamp}.trig"})
          else:
                return JSONResponse(content=r.text, status_code=r.status_code)
     except Exception as e:
          print(f"\n###\nUnexpected error: \n{e = }\n###\n")
          return JSONResponse(content=str(e), status_code=400)

@app.get("/saved_queries",
            dependencies=[Depends(check_auth_or_free_access)],
            include_in_schema=False)
async def get_saved_queries(request: Request,
                            settings: Annotated[Settings, Depends(get_settings)],
                           db_session: Session = Depends(get_db_session)):
    try:
        user_id = request.session.get("id")
        result = find_sparql_query_by_user_id_or_public(user_id, db_session)
        resultList = []
        for one_row in result:
            oneRowDict = one_row.__dict__
            oneRowDict.pop("_sa_instance_state")
            oneRowDict["canDelete"] = one_row.user_id == request.session.get("id") or any(x in request.session.get("role", []) for x in settings.OIDC_ADMIN_ROLE)
            resultList.append(oneRowDict)
        return JSONResponse(content=resultList, status_code=200)
    except Exception as e:
        print(f"Unexpected error: {e}")
        return JSONResponse(content=str(e), status_code=400)

@app.get("/saved_queries/{query_id}",
          dependencies=[Depends(check_auth_or_free_access)],
          include_in_schema=False) 
async def load_saved_query(request: Request, 
                           query_id: str,
                           settings: Annotated[Settings, Depends(get_settings)],
                           db_session: Session = Depends(get_db_session)):
    try:
        result = find_sparql_query_by_id(query_id, db_session)

        if result:
            if(result.public or result.user_id == request.session.get("id") or any(x in request.session.get("role", []) for x in settings.OIDC_ADMIN_ROLE)):
                resultDict = result.__dict__
                resultDict.pop("_sa_instance_state")
                resultDict["canDelete"] = result.user_id == request.session.get("id") or any(x in request.session.get("role", []) for x in settings.OIDC_ADMIN_ROLE)
                return JSONResponse(content=resultDict, status_code=200)
        else:
            return JSONResponse(content=f"Query with ID {query_id} does not exist!", status_code=404)
    except Exception as e:
        print(f"Unexpected error: {e}")
        return JSONResponse(content=str(e), status_code=400)
    
@app.post("/saved_queries",
            dependencies=[Depends(check_auth_or_free_access), Depends(maintainer_or_admin_role)],
            include_in_schema=False)
async def save_query(request: Request,
                    settings: Annotated[Settings, Depends(get_settings)],
                    db_session: Session = Depends(get_db_session)):
    try:
        data = await request.json()
        public = data.get("public", False)
        query = data.get("query", None)
        name = data.get("name", None)

        if not query:
            return JSONResponse(content=f"Cannot save an empty query!", status_code=400)
        
        if not name:
            return JSONResponse(content=f"Name is mandatory!", status_code=400)
        
        user_id = request.session.get("id")
        sparql_query = SparqlQuery(user_id=user_id, query=query, name=name, public=public)
        db_session.add(sparql_query)
        db_session.commit()
        db_session.refresh(sparql_query)
        
        return JSONResponse(content=sparql_query.id, status_code=201)
    except Exception as e:
        print(f"Unexpected error: {e}")
        return JSONResponse(content=str(e), status_code=400)

@app.put("/saved_queries/{query_id}",
          dependencies=[Depends(check_auth_or_free_access), Depends(maintainer_or_admin_role)],
          include_in_schema=False)
async def update_query(request: Request,
                    settings: Annotated[Settings, Depends(get_settings)],
                    db_session: Session = Depends(get_db_session)):
    try:
        query_id = request.path_params.get("query_id")
        data = await request.json()
        public = data.get("public", False)
        query = data.get("query", None)
        
        if not query:
            return JSONResponse(content=f"Cannot save an empty query!", status_code=400)
        
        result = find_sparql_query_by_id(query_id, db_session)
        if result:
            if(result.user_id == request.session.get("id") or any(x in request.session.get("role", []) for x in settings.OIDC_ADMIN_ROLE)):
                result.query = query
                result.public = public
                db_session.commit()
                db_session.refresh(result)
                return JSONResponse(content=result.id, status_code=200)
            else:
                return JSONResponse(content=f"Not allowed to update this query!", status_code=403)
    except Exception as e:
        print(f"Unexpected error: {e}")
        return JSONResponse(content=str(e), status_code=400)

@app.delete("/saved_queries/{query_id}",
            dependencies=[Depends(check_auth_or_free_access), Depends(maintainer_or_admin_role)],
            include_in_schema=False)
async def delete_query(request: Request,
                       settings: Annotated[Settings, Depends(get_settings)],
                    db_session: Session = Depends(get_db_session)):
    try:
        query_id = request.path_params.get("query_id")
        result = find_sparql_query_by_id(query_id, db_session)
        if result:
            if(result.user_id == request.session.get("id") or any(x in request.session.get("role", []) for x in settings.OIDC_ADMIN_ROLE)):
                db_session.delete(result)
                db_session.commit()
                return JSONResponse(content="Query deleted", status_code=200)
            else:
                return JSONResponse(content=f"Not allowed to delete this query!", status_code=403)
    except Exception as e:
        print(f"Unexpected error: {e}")
        return JSONResponse(content=str(e), status_code=400)

@app.post("/query",
          description="Query data in dataset.",
          summary="Query data in dataset",
          dependencies=[Depends(check_auth_or_free_access)],
          include_in_schema=False)  # use axios in frontend to prevent reload page
async def form_query(request: Request, tdb_id: str = Query("Tensile_Tests_Examples"),
                     query: str = Form("SELECT * WHERE {?sub ?pred ?obj .} LIMIT 10"),
                     client: httpx.AsyncClient = Depends(get_client),
                     is_cache: bool = True):

    try:
        # Check if the result is already in the cache. If you don't want a cache, set is_cache to False (in frontend or backend)
        if is_cache:
            result = cache.get(tdb_id + query)
            if result is not None:
                print(f"Found query result in cache")
                return result

        r = await get_jenaconn(tdb_id).query(query, client)

        if r.status_code == 200:
            head, data, raw = extract_queryresults(r)
            
            data = {
                "head": [{"title": column} for column in head],
                "data": data,
                "raw": raw
            }

            # print(data)

            # Store the result in the cache
            cache[tdb_id + query] = JSONResponse(content=data, status_code=200)
            return JSONResponse(content=data, status_code=200)
        else:
            # print(f"\n###{r.text = }\n###\n")
            # print(f"\n###{r.content.decode('utf-8') = }\n###\n")
            return JSONResponse(content=r.text, status_code=r.status_code)

    except JSONDecodeError as e:
        print(f"\n###QUERY_ERROR\n###\n")
        return JSONResponse(content="Query error",
                            status_code=400)  # see QUERY_TIMEOUT argument in docker-compose.yml

    except Exception as e:
        print(f"\n###\nUnexpected error: \n{e = }\n###\n")
        return JSONResponse(content=str(e), status_code=400)


@app.post("/update",
          description="Update data in dataset.",
          summary="Update data in dataset",
          dependencies=[Depends(check_auth_or_free_access), Depends(maintainer_or_admin_role)],
          include_in_schema=False)  # use axios in frontend to prevent reload page
async def form_update(request: Request, role: Annotated[list, Depends(get_user_role)],
                      settings: Annotated[Settings, Depends(get_settings)],
                      update: Annotated[str, Form()],
                      tdb_id: str = Query("Tensile_Tests_Examples"),
                      client: httpx.AsyncClient = Depends(get_client)
                      ):
    if not request.session.get("name"):
        return JSONResponse(content="Not authenticated", status_code=401)

    if not role or (not role == settings.OIDC_ADMIN_ROLE and not role == settings.OIDC_READWRITE_ROLE):
        return JSONResponse(content="Access forbidden", status_code=403)

    try:

        # empty update code won't cause error using Pymantic but in Fuseki console it does (it use ?query if update code is wrong)
        if update.strip():
            r = await get_jenaconn(tdb_id).update(update, client)  # Fuseki does not return a message after 200 OK

            if r.status_code == 204 or r.status_code == 200:
                data = "Update succeeded"

                # Clear the cache
                cache.clear()

                return JSONResponse(content=data, status_code=200)
            if r.status_code != 200:
                # print(f"{r.content = }")
                return JSONResponse(content=r.content.decode("utf-8"), status_code=r.status_code)

        else:
            data = "SPARQL Update: empty"
            return JSONResponse(content=data, status_code=400)


    except Exception as e:
        print(f"\n###\nUnexpected error: \n{e = }\n###\n")
        return JSONResponse(content=str(e), status_code=400)
    
@app.get("/admin",
        description="Admin page with backup and restore functionalities and other admin.",
        dependencies=[Depends(check_auth_or_free_access), Depends(admin_role)],
        include_in_schema=False)
async def admin_page(request: Request, 
                     settings: Annotated[Settings, Depends(get_settings)],
                     db_session: Session = Depends(get_db_session),
                     client: httpx.AsyncClient = Depends(get_client)):
    # Prepare Template for Admin Page
    pass

@app.get("/admin/backup/backup",
         description="Backup with all datasets data and saved queries.",
         dependencies=[Depends(check_auth_or_free_access), Depends(admin_role)],
         include_in_schema=False)
async def backup(request: Request, 
                            settings: Annotated[Settings, Depends(get_settings)],
                            db_session: Session = Depends(get_db_session),
                            client: httpx.AsyncClient = Depends(get_client)):
        try:
            # Backup dataset
            dataset_names = await FusekiConnection.get_all_tdb_ids(client)
            dataset_contents = []
            for dataset_name in dataset_names:
                r = await get_jenaconn(dataset_name).data(client)
                if r.status_code == 200:
                    dataset_contents.append({"name": dataset_name, "data": r.content.decode("utf-8")})
                else:
                    print(f"Error backupping dataset {dataset_name}")
                    continue
            # Backup saved queries
            result = find_all_sparql_query(db_session)
            saved_queries = []
            for one_row in result:
                oneRowDict = one_row.__dict__
                oneRowDict.pop("_sa_instance_state")
                oneRowDict.pop("user_id")
                oneRowDict.pop("id")
                saved_queries.append(oneRowDict)

            backup = {
                "datasets": dataset_contents,
                "queries": saved_queries
            }
            current_timestamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
            # Save backup as JSON file
            with open(f"ontodocker_backup_{current_timestamp}.json", "w") as file:
                json.dump(backup, file)
            # Return the JSON file as a download
            return FileResponse(f"ontodocker_backup_{current_timestamp}.json", media_type="application/json", filename=f"ontodocker_backup_{current_timestamp}.json")

            
    
        except Exception as e:
            print(f"\n###\nUnexpected error: \n{e = }\n###\n")
            return JSONResponse(content=str(e), status_code=400)
        
@app.post("/admin/backup/restore",
            description="Restore from a previous backup with its data and saved queries.",
            dependencies=[Depends(check_auth_or_free_access), Depends(admin_role)],
            include_in_schema=False)
async def restore_dataset(request: Request,
                            settings: Annotated[Settings, Depends(get_settings)],
                            db_session: Session = Depends(get_db_session),
                            client: httpx.AsyncClient = Depends(get_client)):

        # Clear all existing datasets and saved queries
        try:
            # Clear all datasets
            dataset_names = await FusekiConnection.get_all_tdb_ids(client)
            for dataset_name in dataset_names:
                r = await get_jenaconn(dataset_name).destroy_ds(client)
                if r.status_code == 200:
                    # Clear the cache
                    cache.clear()
                else:
                    print(f"Error clearing dataset {dataset_name}")
                    continue
            # Clear all saved queries
            result = find_all_sparql_query(db_session)
            for one_row in result:
                db_session.delete(one_row)
            db_session.commit()
        except Exception as e:
            print(f"\n###\nUnexpected error during clear: \n{e = }\n###\n")
            return JSONResponse(content=str(e), status_code=400)
        try:
            # Get the uploaded file
            uploaded_file = await request.form()
            file = uploaded_file["file"]
            contents = await file.read()
            backup = json.loads(contents)
            # Restore datasets
            for dataset in backup["datasets"]:
                # Create dataset
                r = await get_jenaconn(dataset["name"]).create_ds(client)
                r1 = await get_jenaconn(dataset["name"]).upload_data(dataset["data"], client)
                if r.status_code == 200 and r1.status_code == 200:
                    # Clear the cache
                    cache.clear()
                else:
                    print(f"Error restoring dataset {dataset['name']}")
                    continue
            # Restore saved queries
            for query in backup["queries"]:
                sparql_query = SparqlQuery(user_id=request.session.get("id"), query=query["query"], name=query["name"], public=query["public"])
                db_session.add(sparql_query)
                db_session.commit()
                db_session.refresh(sparql_query)
            return JSONResponse(content="Restore succeeded", status_code=200)
        except Exception as e:
            print(f"\n###\nUnexpected error during restore: \n{e = }\n###\n")
            return JSONResponse(content=str(e), status_code=400)


@app.post("/upload",
          description="Upload RDF data (.rdf or .ttl) to Fuseki Jena dataset.",
          summary="Upload RDF data (.rdf or .ttl) to Fuseki Jena dataset",
          dependencies=[Depends(check_auth_or_free_access), Depends(maintainer_or_admin_role)],
          include_in_schema=False)  # use axios in frontend to prevent reload page
async def upload_file(request: Request, role: Annotated[list, Depends(get_user_role)],
                      settings: Annotated[Settings, Depends(get_settings)],
                      tdb_name: str = "jena", tdb_id: str = Query(), namedGraphUpload: Optional[str] = Form(None), file: UploadFile = File(...),
                      client: httpx.AsyncClient = Depends(get_client)
                      ):

    # print(f"\n#####\nUploading files...\n#####\n")

    try:

        if not namedGraphUpload or len(namedGraphUpload) == 0:
            named_graph = "default"
        else:
            named_graph = namedGraphUpload

        if named_graph.startswith("<") or named_graph.endswith(">"):
            return JSONResponse("IRI must not start with < and end with > and must be a valid URI", status_code=400)

        # Frontend checked, but check again in backend in case someone bypasses it via script upload
        if not is_file_allowed(file.filename):
            return JSONResponse("Not a file or filetype not allowed", status_code=422)

        # Save file
        upload_dir = f'{os.getcwd()}/upload/{tdb_name}/{tdb_id}/'
        os.makedirs(upload_dir, exist_ok=True)
        filename = secure_filename(file.filename)
        filepath = os.path.join(upload_dir, filename)

        contents = await file.read()
        with open(filepath, "wb") as f:
            start_time = time.time()  # Record the start time
            f.write(contents)
            end_time = time.time()  # Record the end time
            elapsed_time = end_time - start_time  # Calculate the elapsed time
            print(f"\n#####\nElapsed time (Write): {elapsed_time} seconds\n#####\n")

        # Import to triplestore

        print(f"\n####\nimport to triplestore\n####\n")
        if tdb_name == "jena":
            print(f"\n####\nIn Jena {tdb_name = }\n####\n")
            r = await get_jenaconn(tdb_id).upload(filepath, named_graph, client)
            if r.status_code == 200:
                # Clear the cache
                cache.clear()

            await get_jenaconn(tdb_id).get_vowl(client)

            return JSONResponse(content=r.content.decode("utf-8"), status_code=r.status_code)

        else:
            raise HTTPException(status_code=404, detail="Triplestore not exist")

    except Exception as e:
        print(f'{e = }')
        return JSONResponse(content=str(e), status_code=400)

@app.get('/admin/backup',
         description="Administration page for backup and restore",
         dependencies=[Depends(check_auth_or_free_access), Depends(admin_role)],
         include_in_schema=False 
)
async def admin_backup(response: Response, request: Request, settings: Annotated[Settings, Depends(get_settings)],
                   client: httpx.AsyncClient = Depends(get_client)):
    
    # check Fuseki triplestore for datasets
    tdb_ids_jena = None
    try:
        tdb_ids_jena = await FusekiConnection.get_all_tdb_ids(client)
    except Exception as e:
        print(f"\n####\nFuseki:\nERROR: {str(e)}\n####\n")

    # set variables for navbar
    name = request.session.get("name", "anonymous")
    api_key = request.session.get("api_key", "")
    role = request.session.get("role", settings.OIDC_ADMIN_ROLE if os.getenv("ANONYMOUS_IS_ADMIN", "false") == "true" else None)
        

    if tdb_ids_jena and not role == settings.OIDC_ADMIN_ROLE:
        tdb_ids_jena = [item for item in tdb_ids_jena if
                        "-mem" not in item and
                        "_mem" not in item
                        ]

    return templates.TemplateResponse("admin_backup.html", {"request": request,
                                                     "name": name,
                                                     "tdb_ids_jena": tdb_ids_jena,
                                                     "api_key": api_key if api_key else "",
                                                     "api_key_default_valid_days": settings.JWT_DEFAULT_DAYS_VALID,
                                                     "api_key_valid_to": decode_token(api_key).get("exp") if api_key else "-",
                                                     "role": role,
                                                     "user_identifier": request.session.get("user_identifier", ""),
                                                     "provider": request.session.get("provider", ""),
                                                     "isAdminRole": role == settings.OIDC_ADMIN_ROLE,
                                                     "isReadWriteRole": role == settings.OIDC_READWRITE_ROLE,
                                                     "isReadOnlyRole": not role or role == settings.OIDC_READONLY_ROLE
                                                     })

@app.get("/admin/fuseki",
            description="Administration page for Fuseki",
            dependencies=[Depends(check_auth_or_free_access), Depends(admin_role)],
            include_in_schema=False)
async def admin_fuseki(request: Request,
                        settings: Annotated[Settings, Depends(get_settings)],
                        db_session: Session = Depends(get_db_session),
                        client: httpx.AsyncClient = Depends(get_client)):
    # check Fuseki triplestore for datasets
    tdb_ids_jena = None
    try:
        tdb_ids_jena = await FusekiConnection.get_all_tdb_ids(client)
    except Exception as e:
        print(f"\n####\nFuseki:\nERROR: {str(e)}\n####\n")

    # set variables for navbar
    name = request.session.get("name", "anonymous")
    api_key = request.session.get("api_key", "")
    role = request.session.get("role", settings.OIDC_ADMIN_ROLE if os.getenv("ANONYMOUS_IS_ADMIN", "false") == "true" else None)
        

    if tdb_ids_jena and not role == settings.OIDC_ADMIN_ROLE:
        tdb_ids_jena = [item for item in tdb_ids_jena if
                        "-mem" not in item and
                        "_mem" not in item
                        ]

    return templates.TemplateResponse("admin_fuseki.html", {"request": request,
                                                     "name": name,
                                                     "tdb_ids_jena": tdb_ids_jena,
                                                     "api_key": api_key if api_key else "",
                                                     "api_key_default_valid_days": settings.JWT_DEFAULT_DAYS_VALID,
                                                     "api_key_valid_to": decode_token(api_key).get("exp") if api_key else "-",
                                                     "role": role,
                                                     "user_identifier": request.session.get("user_identifier", ""),
                                                     "provider": request.session.get("provider", ""),
                                                     "isAdminRole": role == settings.OIDC_ADMIN_ROLE,
                                                     "isReadWriteRole": role == settings.OIDC_READWRITE_ROLE,
                                                     "isReadOnlyRole": not role or role == settings.OIDC_READONLY_ROLE
                                                     })

@app.get("/admin/fuseki/rest/status")
async def admin_fuseki_status(request: Request,
                              settings: Annotated[Settings, Depends(get_settings)],
                              db_session: Session = Depends(get_db_session),
                              client: httpx.AsyncClient = Depends(get_client)):
    r = await FusekiConnection.get_server_status(client)
    if r.status_code == 200:
        return JSONResponse(content=r.json(), status_code=200)
    else:
        return JSONResponse(content=r.text, status_code=r.status_code)

@app.post("/admin/fuseki/rest/restart",
            description="Restart Fuseki",
            dependencies=[Depends(check_auth_or_free_access), Depends(admin_role)],
            include_in_schema=False)
async def admin_fuseki_restart(request: Request,
                                settings: Annotated[Settings, Depends(get_settings)],
                                db_session: Session = Depends(get_db_session),
                                client: httpx.AsyncClient = Depends(get_client)):
    try:
        FusekiConnection.restart_fuseki_container()
        return JSONResponse(content="Fuseki restarting", status_code=200)
    except Exception as e:
        print(f"\n####\nFuseki:\nERROR: {str(e)}\n####\n")
        return JSONResponse(content=str(e), status_code=400)

@app.get('/admin/ckan',
         description="Administration page for ckan",
         dependencies=[Depends(check_auth_or_free_access), Depends(admin_role)],
         include_in_schema=False 
)
async def admin_ckan(response: Response, request: Request, settings: Annotated[Settings, Depends(get_settings)],
                   client: httpx.AsyncClient = Depends(get_client)):
    
    # check Fuseki triplestore for datasets
    tdb_ids_jena = None
    try:
        tdb_ids_jena = await FusekiConnection.get_all_tdb_ids(client)
    except Exception as e:
        print(f"\n####\nFuseki:\nERROR: {str(e)}\n####\n")

    # set variables for navbar
    name = request.session.get("name", "anonymous")
    api_key = request.session.get("api_key", "")
    role = request.session.get("role", settings.OIDC_ADMIN_ROLE if os.getenv("ANONYMOUS_IS_ADMIN", "false") == "true" else None)
        

    if tdb_ids_jena and not role == settings.OIDC_ADMIN_ROLE:
        tdb_ids_jena = [item for item in tdb_ids_jena if
                        "-mem" not in item and
                        "_mem" not in item
                        ]

    return templates.TemplateResponse("admin_ckan.html", {"request": request,
                                                     "name": name,
                                                     "tdb_ids_jena": tdb_ids_jena,
                                                     "api_key": api_key if api_key else "",
                                                     "api_key_default_valid_days": settings.JWT_DEFAULT_DAYS_VALID,
                                                     "api_key_valid_to": decode_token(api_key).get("exp") if api_key else "-",
                                                     "role": role,
                                                     "user_identifier": request.session.get("user_identifier", ""),
                                                     "provider": request.session.get("provider", ""),
                                                     "isAdminRole": role == settings.OIDC_ADMIN_ROLE,
                                                     "isReadWriteRole": role == settings.OIDC_READWRITE_ROLE,
                                                     "isReadOnlyRole": not role or role == settings.OIDC_READONLY_ROLE
                                                     })

@app.get('/admin/ckan/rest/current',
         description="Get current CKAN configuration",
         dependencies=[Depends(check_auth_or_free_access), Depends(admin_role)],
         include_in_schema=False 
)
async def admin_ckan_rest_current(response: Response, request: Request, settings: Annotated[Settings, Depends(get_settings)],
                                  db_session: Session = Depends(get_db_session),
                                client: httpx.AsyncClient = Depends(get_client)):
        try:
            ckan_url = get_application_store_by_key(db_session, "ckan_url")
            ckan_api_key = get_application_store_by_key(db_session, "ckan_api_key")
            ckan_organization_id = get_application_store_by_key(db_session, "ckan_organization_id")
            ckan_group_ids = json.loads(get_application_store_by_key(db_session, "ckan_group_ids", "[]"))
            ckan_api_format = get_application_store_by_key(db_session, "ckan_api_format", "default")
            ckan_config = {
                "ckan_url": ckan_url,
                "ckan_api_key": ckan_api_key,
                "ckan_organization_id": ckan_organization_id,
                "ckan_group_ids": ckan_group_ids,
                "ckan_api_format": ckan_api_format
            }
            return JSONResponse(content=ckan_config, status_code=200)
        except Exception as e:
            print(f"\n####\nCKAN:\nERROR: {str(e)}\n####\n")
            return JSONResponse(content=str(e), status_code=400)
        
@app.post('/admin/ckan/rest/test',
          description="Test CKAN configuration",
          dependencies=[Depends(check_auth_or_free_access), Depends(admin_role)],
            include_in_schema=False)
async def admin_ckan_rest_test(request: Request,
                               settings: Annotated[Settings, Depends(get_settings)],
                               db_session: Session = Depends(get_db_session),
                               client: httpx.AsyncClient = Depends(get_client)):
        data = await request.json()
        ckanUrl = data.get("ckanUrl", None)
        ckanApiKey = data.get("ckanApiKey", None)
        if not ckanUrl or not ckanApiKey or len(ckanUrl) == 0 or len(ckanApiKey) == 0:
            return JSONResponse(content="CKAN URL and API Key must be set!", status_code=400)
        
        if ckanUrl[-1] == "/":
            ckanUrl = ckanUrl[:-1]
        try:
            ckan_req = urllib2.Request(f'{ckanUrl}/api/3', headers={"Authorization": ckanApiKey})
            urllib2.urlopen(ckan_req)
        except urllib2.HTTPError as e:
            return JSONResponse(content=f"HTTP error: {e.code} - {e.reason}", status_code=e.code)
        except urllib2.URLError as e:
            return JSONResponse(content=f"URL error: {e.reason}", status_code=400)
        except ValueError as e:
            return JSONResponse(content=f"URL error: {e}", status_code=400)
        ckan_req = urllib2.Request(f'{ckanUrl}/api/3', headers={"Authorization": ckanApiKey})
        try:
            responseDict = {}
            user_ckan_req = urllib2.Request(f'{ckanUrl}/api/3/action/user_show', headers={"Authorization": ckanApiKey})
            try:    
                user_response = urllib2.urlopen(user_ckan_req)
                userRespDict = json.loads(user_response.read())
                if userRespDict["success"]:
                    responseDict["user"] = userRespDict.get("result", {}).get("name", "not given")
                    organization_ckan_req = urllib2.Request(f'{ckanUrl}/api/3/action/organization_list_for_user', headers={"Authorization": ckanApiKey})
                    try:
                        organization_response = urllib2.urlopen(organization_ckan_req)
                        organizationRespDict = json.loads(organization_response.read())
                        if organizationRespDict["success"]:
                            organizationList = organizationRespDict.get("result", [])
                            organizationDictList = []
                            for organizationDict in organizationList:
                                organizationDictList.append({"id": organizationDict["id"], "name": organizationDict["title"]})
                            responseDict["organizations"] = organizationDictList
                            group_ckan_req = urllib2.Request(f'{ckanUrl}/api/3/action/group_list_authz', headers={"Authorization": ckanApiKey})
                            try:
                                group_response = urllib2.urlopen(group_ckan_req)
                                groupRespDict = json.loads(group_response.read())
                                if groupRespDict["success"]:
                                    groupList = groupRespDict.get("result", [])
                                    groupDictList = []
                                    for groupDict in groupList:
                                        groupDictList.append({"id": groupDict["id"], "name": groupDict["title"]})
                                    responseDict["groups"] = groupDictList
                                    return JSONResponse(content=responseDict, status_code=200)
                                else:
                                    return JSONResponse(content=f"Unknown error getting group information with the given API Key (response is not success)", status_code=400)
                            except urllib2.HTTPError as e:
                                return JSONResponse(content=f"Unknown error getting group information with the given API Key", status_code=400)
                    except urllib2.HTTPError as e:
                        return JSONResponse(content=f"Unknown error getting organization information with the given API Key (response is not success)", status_code=400)
                else:    
                    return JSONResponse(content=f"Unknown error getting user information with the given API Key (response is not success)", status_code=400)
            except urllib2.HTTPError as e:
                if e.code == 403:
                    return JSONResponse(content=f"Given API Key is not valid", status_code=400)
                else:
                    return JSONResponse(content=f"Unknown error getting user information with the given API Key", status_code=400)
        except urllib2.HTTPError as e:
            return JSONResponse(content=f"Could not reach CKAN API at {ckanUrl}/api/3 (HTTP Error {e.code})", status_code=400)
        except urllib2.URLError as e:
            return JSONResponse(content=f"Could not reach CKAN API at {ckanUrl}/api/3", status_code=400)

@app.post("/admin/ckan/rest/save",
          description="Save CKAN configuration",
          dependencies=[Depends(check_auth_or_free_access), Depends(admin_role)],
          include_in_schema=False)
async def admin_ckan_rest_save(request: Request,
                               settings: Annotated[Settings, Depends(get_settings)],
                               db_session: Session = Depends(get_db_session),
                               client: httpx.AsyncClient = Depends(get_client)):
        data = await request.json()
        ckanUrl = data.get("ckanUrl", None)
        ckanApiKey = data.get("ckanApiKey", None)
        ckanOrganizationId = data.get("ckanOrganizationId", None)
        ckanGroupIds = data.get("ckanGroupIds", [])
        ckanApiFormat = data.get("ckanApiFormat", [])
        if not ckanUrl or not ckanApiKey or len(ckanUrl) == 0 or len(ckanApiKey) == 0 or not ckanOrganizationId or len(ckanOrganizationId) == 0:
            return JSONResponse(content="CKAN URL, API Key and Organization ID must be set!", status_code=400)
        if ckanUrl[-1] == "/":
            ckanUrl = ckanUrl[:-1]
        create_or_update_application_store_by(db_session, "ckan_url", ckanUrl)
        create_or_update_application_store_by(db_session, "ckan_api_key", ckanApiKey)
        create_or_update_application_store_by(db_session, "ckan_organization_id", ckanOrganizationId)
        create_or_update_application_store_by(db_session, "ckan_group_ids", json.dumps(ckanGroupIds))
        create_or_update_application_store_by(db_session, "ckan_api_format", ckanApiFormat)
        return JSONResponse(content="CKAN configuration saved", status_code=200)
        

@app.get('/admin/users',
         description="Administration page for users",
         dependencies=[Depends(check_auth_or_free_access), Depends(admin_role)],
         include_in_schema=False 
)
async def admin_users(response: Response, request: Request, settings: Annotated[Settings, Depends(get_settings)],
                      db_session: Session = Depends(get_db_session),
                   client: httpx.AsyncClient = Depends(get_client)):
    
    # check Fuseki triplestore for datasets
    tdb_ids_jena = None
    try:
        tdb_ids_jena = await FusekiConnection.get_all_tdb_ids(client)
    except Exception as e:
        print(f"\n####\nFuseki:\nERROR: {str(e)}\n####\n")

    # set variables for navbar
    name = request.session.get("name", "anonymous")
    api_key = request.session.get("api_key", "")
    role = request.session.get("role", settings.OIDC_ADMIN_ROLE if os.getenv("ANONYMOUS_IS_ADMIN", "false") == "true" else None)
        

    if tdb_ids_jena and not role == settings.OIDC_ADMIN_ROLE:
        tdb_ids_jena = [item for item in tdb_ids_jena if
                        "-mem" not in item and
                        "_mem" not in item
                        ]
        
    available_providers = []
    # Add identifier helptext to every provider
    for provider in get_all_sso_providers(db_session):
        identifier_helptext = ""
        if provider.type == "keycloak":
            identifier_helptext = "Keycloak Email address or username"
        elif provider.type == "orcid":
            identifier_helptext = "ORC iD"
        available_providers.append({
            "id": provider.id,
            "type": provider.type,
            "client_id": provider.client_id,
            "name": provider.name,
            "enabled": provider.enabled,
            "new_user_role": provider.new_user_role,
            "identifier_helptext": identifier_helptext
        })
        

    users = get_all_users_order_by_name(db_session)
    # Iterate users and add to return object fields for display
    return_users = []
    for user in users:
        return_users.append({
            "id": user.id,
            "name": user.name,
            "sso_provider_id": user.sso_provider_id,
            "user_identifier": user.user_identifier,
            "role": user.role,
            "last_login_time": datetime.datetime.fromtimestamp(user.last_login_timestamp, tz=datetime.UTC).astimezone(zoneinfo.ZoneInfo('Europe/Berlin')).strftime('%Y-%m-%d %H:%M:%S') if user.last_login_timestamp else "-",
        })

    return templates.TemplateResponse("admin_users.html", {"request": request,
                                                     "name": name,
                                                     "tdb_ids_jena": tdb_ids_jena,
                                                     "api_key": api_key if api_key else "",
                                                     "api_key_default_valid_days": settings.JWT_DEFAULT_DAYS_VALID,
                                                     "api_key_valid_to": decode_token(api_key).get("exp") if api_key else "-",
                                                     "role": role,
                                                     "user_identifier": request.session.get("user_identifier", ""),
                                                     "provider": request.session.get("provider", ""),
                                                     "available_providers": available_providers,
                                                     "users": return_users,
                                                     "isAdminRole": role == settings.OIDC_ADMIN_ROLE,
                                                     "isReadWriteRole": role == settings.OIDC_READWRITE_ROLE,
                                                     "isReadOnlyRole": not role or role == settings.OIDC_READONLY_ROLE
                                                     })

@app.post('/admin/users',
          description="Create a new user",
          dependencies=[Depends(check_auth_or_free_access), Depends(admin_role)],
            include_in_schema=False)
async def create_user(request: Request,
                        settings: Annotated[Settings, Depends(get_settings)],
                        db_session: Session = Depends(get_db_session)):
        try:
            data = await request.json()
            sso_provider = data.get("sso_provider", None)
            user_identifier = data.get("user_identifier", None)
            user_password = data.get("user_password", None)
            name = data.get("name", None)
            role = data.get("role", None)
            if not sso_provider:
                return JSONResponse(content=f"SSO Provider must be selected!", status_code=400)
            if not user_identifier:
                return JSONResponse(content=f"User Identifier must be set!", status_code=400)
            if not name:
                return JSONResponse(content=f"Name must be set!", status_code=400)
            if not role:
                return JSONResponse(content=f"Role must be selected!", status_code=400)
            if role not in settings.OIDC_REQUIRED_ROLES:
                return JSONResponse(content=f"Role must be one of the given ones!", status_code=400)
            if sso_provider == "local" and (not user_password or len(user_password) < 8):
                return JSONResponse(content=f"Password must be at least 8 characters long!", status_code=400)
            
            # Check if user with same sso_provider and user_identifier already exists
            result = get_user_by_sso_provider_and_user_identifier(sso_provider, user_identifier, db_session)
            if result:
                return JSONResponse(content=f"User with same SSO-Provider and User Identifier already exists!", status_code=400)
            hashed_password = bcrypt.hashpw(user_password.encode("utf-8"), bcrypt.gensalt())
            sso_provider_id = None if sso_provider is None or sso_provider == "local" else int(sso_provider)
            user = User(sso_provider_id=sso_provider_id, user_identifier=user_identifier, password=hashed_password.decode("utf-8"), name=name, role=role)
            db_session.add(user)
            db_session.commit()
            db_session.refresh(user)
            return JSONResponse(content=user.id, status_code=201)
        except Exception as e:
            print(f"Unexpected error: {e}")
            return JSONResponse(content=str(e), status_code=400)
        
        
@app.put('/admin/users/{user_id}',
          description="Update a user",
          dependencies=[Depends(check_auth_or_free_access), Depends(admin_role)],
          include_in_schema=False)
async def update_user(request: Request,
                        settings: Annotated[Settings, Depends(get_settings)],
                        db_session: Session = Depends(get_db_session)):
        try:
            user_id = request.path_params.get("user_id")
            data = await request.json()
            sso_provider = data.get("sso_provider", None)
            user_identifier = data.get("user_identifier", None)
            user_password = data.get("user_password", None)
            name = data.get("name", None)
            role = data.get("role", None)
            if not sso_provider:
                return JSONResponse(content=f"SSO Provider must be selected!", status_code=400)
            if not user_identifier:
                return JSONResponse(content=f"User Identifier must be set!", status_code=400)
            if not name:
                return JSONResponse(content=f"Name must be set!", status_code=400)
            if not role:
                return JSONResponse(content=f"Role must be selected!", status_code=400)
            if role not in settings.OIDC_REQUIRED_ROLES:
                return JSONResponse(content=f"Role must be one of the given ones!", status_code=400)
            if sso_provider == "local" and user_password and len(user_password) > 0 and len(user_password) < 8:
                return JSONResponse(content=f"Password must be at least 8 characters long!", status_code=400)
            result = get_user_by_id(user_id, db_session)
            if result:
                result.sso_provider_id = None if sso_provider is None or sso_provider == "local" else int(sso_provider)
                result.user_identifier = user_identifier
                if user_password and len(user_password) > 0:
                    hashed_password = bcrypt.hashpw(user_password.encode("utf-8"), bcrypt.gensalt())
                    result.password = hashed_password.decode("utf-8")
                result.name = name
                result.role = role
                db_session.commit()
                db_session.refresh(result)
                return JSONResponse(content=result.id, status_code=200)
            else:
                return JSONResponse(content=f"User with ID {user_id} does not exist!", status_code=404)
        except Exception as e:
            print(f"Unexpected error: {e}")
            return JSONResponse(content=str(e), status_code=400)
        
@app.post('/admin/users/sso/keycloak',
          description="Create a new Keycloak SSO Provider",
          dependencies=[Depends(check_auth_or_free_access), Depends(admin_role)],
          include_in_schema=False)
async def create_keycloak_sso_provider(request: Request,
                        settings: Annotated[Settings, Depends(get_settings)],
                        db_session: Session = Depends(get_db_session)):
        try:
            data = await request.json()
            name = data.get("name", None)
            server_metadata_url = data.get("server_metadata_url", None)
            client_id = data.get("client_id", None)
            client_secret = data.get("client_secret", None)
            enabled = data.get("enabled", False)
            if not name:
                return JSONResponse(content=f"Name must be set!", status_code=400)
            if not server_metadata_url:
                return JSONResponse(content=f"Metadata URL must be set!", status_code=400)
            if not client_id:
                return JSONResponse(content=f"Client ID must be set!", status_code=400)
            if not client_secret:
                return JSONResponse(content=f"Client Secret must be set!", status_code=400)
            # Check if SSO Provider with same name already exists
            result = get_sso_provider_by_name(name, db_session)
            if result:
                return JSONResponse(content=f"SSO Provider with same name already exists!", status_code=400)
            sso_provider = SSOProvider(type="keycloak", name=name, server_metadata_url=server_metadata_url, client_id=client_id, client_secret=client_secret, scope="openid profile", enabled=enabled)
            db_session.add(sso_provider)
            db_session.commit()
            db_session.refresh(sso_provider)
            return JSONResponse(content=sso_provider.id, status_code=201)
        except Exception as e:
            print(f"Unexpected error: {e}")
            return JSONResponse(content=str(e), status_code=400)
        
@app.post('/admin/users/sso/orcid',
            description="Create a new ORCID SSO Provider",
            dependencies=[Depends(check_auth_or_free_access), Depends(admin_role)],
            include_in_schema=False)
async def create_orcid_sso_provider(request: Request,
                        settings: Annotated[Settings, Depends(get_settings)],
                        db_session: Session = Depends(get_db_session)):
        try:
            data = await request.json()
            name = data.get("name", None)
            server_metadata_url = data.get("server_metadata_url", None)
            client_id = data.get("client_id", None)
            client_secret = data.get("client_secret", None)
            enabled = data.get("enabled", False)
            if not name:
                return JSONResponse(content=f"Name must be set!", status_code=400)
            if not server_metadata_url:
                return JSONResponse(content=f"Metadata URL must be set!", status_code=400)
            if not client_id:
                return JSONResponse(content=f"Client ID must be set!", status_code=400)
            if not client_secret:
                return JSONResponse(content=f"Client Secret must be set!", status_code=400)
            # Check if SSO Provider with same name already exists
            result = get_sso_provider_by_name(name, db_session)
            if result:
                return JSONResponse(content=f"SSO Provider with same name already exists!", status_code=400)
            sso_provider = SSOProvider(type="orcid", name=name, server_metadata_url=server_metadata_url, client_id=client_id, client_secret=client_secret, scope="openid /authenticate", enabled=enabled)
            db_session.add(sso_provider)
            db_session.commit()
            db_session.refresh(sso_provider)
            return JSONResponse(content=sso_provider.id, status_code=201)
        except Exception as e:
            print(f"Unexpected error: {e}")
            return JSONResponse(content=str(e), status_code=400)
        
@app.post('/admin/users/sso/{sso_id}/enabled',
            description="Enable or disable a SSO Provider",
            dependencies=[Depends(check_auth_or_free_access), Depends(admin_role)],
            include_in_schema=False)
async def enable_disable_sso_provider(request: Request,
                        settings: Annotated[Settings, Depends(get_settings)],
                        db_session: Session = Depends(get_db_session)):
        try:
            sso_id = request.path_params.get("sso_id")
            data = await request.json()
            enabled = data.get("enabled", False)
            result = get_sso_provider_by_id(sso_id, db_session)
            if result:
                result.enabled = enabled
                db_session.commit()
                db_session.refresh(result)
                if enabled:
                    return JSONResponse(content=f"SSO Provider {result.name} enabled!", status_code=200)
                else:
                    return JSONResponse(content=f"SSO Provider {result.name} disabled!", status_code=200)
            else:
                return JSONResponse(content=f"SSO Provider with ID {sso_id} does not exist!", status_code=404)
        except Exception as e:
            print(f"Unexpected error: {e}")
            return JSONResponse(content=str(e), status_code=400)
        
@app.put('/admin/users/sso/{sso_id}',
            description="Update the SSO Provider",
            dependencies=[Depends(check_auth_or_free_access), Depends(admin_role)],
            include_in_schema=False)
async def update_sso_provider_name(request: Request,
                        settings: Annotated[Settings, Depends(get_settings)],
                        db_session: Session = Depends(get_db_session)):
        try:
            sso_id = request.path_params.get("sso_id")
            data = await request.json()
            name = data.get("name", None)
            new_user_role = data.get("new_user_role", None)
            if new_user_role and new_user_role not in settings.OIDC_REQUIRED_ROLES:
                return JSONResponse(content=f"Role must be one of the given ones!", status_code=400)
            if not name:
                return JSONResponse(content=f"Name is mandatory!", status_code=400)
            result = get_sso_provider_by_id(sso_id, db_session)
            if result:
                # Check if Provider with same name exists
                result_exists = get_sso_provider_by_name(name, db_session)
                if result_exists and result_exists.id != int(sso_id):
                    return JSONResponse(content=f"SSO Provider with name {name} already exists!", status_code=400)
                result.name = name
                result.new_user_role = new_user_role
                db_session.commit()
                db_session.refresh(result)
                return JSONResponse(content=f"SSO Provider {name} updated!", status_code=200)
            else:
                return JSONResponse(content=f"SSO Provider with ID {sso_id} does not exist!", status_code=404)
        except Exception as e:
            print(f"Unexpected error: {e}")
            return JSONResponse(content=str(e), status_code=400)
        
@app.delete('/admin/users/sso/{sso_id}',
            description="Delete a SSO Provider",
            dependencies=[Depends(check_auth_or_free_access), Depends(admin_role)],
            include_in_schema=False)
async def delete_sso_provider(request: Request,
                        settings: Annotated[Settings, Depends(get_settings)],
                        db_session: Session = Depends(get_db_session)):
        try:
            sso_id = request.path_params.get("sso_id")
            result = get_sso_provider_by_id(sso_id, db_session)
            if result:
                provider_name = result.name
                # Set all users with this SSO Provider to None
                users = get_users_by_sso_provider_id(sso_id, db_session)
                users_count = len(users)
                for user in users:
                    user.sso_provider_id = None
                    db_session.commit()
                    db_session.refresh(user)
                # Delete the SSO Provider
                db_session.delete(result)
                db_session.commit()
                return JSONResponse(content=f"SSO Provider {provider_name} deleted! {users_count} users updated ", status_code=200)
            else:
                return JSONResponse(content=f"SSO Provider with ID {sso_id} does not exist!", status_code=404)
        except Exception as e:
            print(f"Unexpected error: {e}")
            return JSONResponse(content=str(e), status_code=400)

        
# Delete user
@app.delete('/admin/users/{user_id}',
            description="Delete a user",
            dependencies=[Depends(check_auth_or_free_access), Depends(admin_role)],
            include_in_schema=False)
async def delete_user(request: Request,
                        settings: Annotated[Settings, Depends(get_settings)],
                        db_session: Session = Depends(get_db_session)):
        try:
            user_id = request.path_params.get("user_id")
            result = get_user_by_id(user_id, db_session)
            if result:
                # Delete all saved queries of the user
                result_queries = find_sparql_query_by_user(user_id, db_session)
                for one_row in result_queries:
                    db_session.delete(one_row)
                # Delete the user
                db_session.delete(result)
                db_session.commit()
                return JSONResponse(content="User deleted!", status_code=200)
            else:
                return JSONResponse(content=f"User with ID {user_id} does not exist!", status_code=404)
        except Exception as e:
            print(f"Unexpected error: {e}")
            return JSONResponse(content=str(e), status_code=400)

@app.exception_handler(401)
async def custom_401_handler(request: Request, __):
    if "/api/" in request.url.path:
        return JSONResponse(content="401 - Unauthorized", status_code=status.HTTP_401_UNAUTHORIZED)
    return templates.TemplateResponse("401.html", {"request": request}, status_code=status.HTTP_401_UNAUTHORIZED)


@app.exception_handler(403)
async def custom_403_handler(request: Request, __):
    if "/api/" in request.url.path:
        return JSONResponse(content="403 - Not allowed", status_code=status.HTTP_403_FORBIDDEN)
    return templates.TemplateResponse("403.html", {"request": request}, status_code=status.HTTP_403_FORBIDDEN)


@app.exception_handler(404)
async def custom_404_handler(request: Request, exc):
    if "/api/" in request.url.path:
        return JSONResponse(content="404 - Not found", status_code=status.HTTP_404_NOT_FOUND)
    return templates.TemplateResponse("404.html", {"request": request}, status_code=status.HTTP_404_NOT_FOUND)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return templates.TemplateResponse("422.html", {"request": request, "error": jsonable_encoder(
        {"detail": exc.errors(), "body": exc.body})}, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)


@app.exception_handler(500)
async def custom_500_handler(request: Request, __):
    if "/api/" in request.url.path:
        return JSONResponse(content="500 - Internal Server Error", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
    return templates.TemplateResponse("500.html", {"request": request}, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@app.exception_handler(503)
async def custom_503_handler(request: Request, __):
    if "/api/" in request.url.path:
        return JSONResponse(content="503 - Service unavailable", status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return templates.TemplateResponse("503.html", {"request": request}, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)


@app.exception_handler(504)
async def custom_504_handler(request: Request, __):
    if "/api/" in request.url.path:
        return JSONResponse(content="504 - Gateway Timeout", status_code=status.HTTP_504_GATEWAY_TIMEOUT)
    return templates.TemplateResponse("504.html", {"request": request}, status_code=status.HTTP_504_GATEWAY_TIMEOUT)
