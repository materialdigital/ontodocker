import asyncio
import os
import time
from json import JSONDecodeError
import httpx
from typing import Annotated
from config import get_settings, Settings
from typing import Optional
import datetime

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
from db import User, filter_users, SparqlQuery, find_all_sparql_query, find_sparql_query_by_user_id_or_public, find_sparql_query_by_id

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

cache = TTLCache(maxsize=500, ttl=1)

app = FastAPI(title="Ontodocker App", version="1.0.0", description=description)

session_time_days = int(os.environ.get("MAX_SESSION_TIME_IN_DAYS", 14))
app.add_middleware(SessionMiddleware, max_age=session_time_days * 24 * 60 * 60,
                   secret_key=hashlib.sha256(os.environ.get("JWT_SECRET_KEY", secrets.token_urlsafe(32)).encode()).hexdigest()) 
# max_age is by default set to 14 days, this should be less than the "SSO
# Session Idle" time in the Keycloak settings. so that if the session expires after the desired time, the user will
# be redirected to the Keycloak login page
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

    # remove default dataset "ds" in Fuseki
    async with httpx.AsyncClient() as client:
        try:
            tdb_ids_jena = await FusekiConnection.get_all_tdb_ids(client)
            if "ds" in tdb_ids_jena:
                await get_jenaconn("ds").destroy_ds(client)
        except Exception as e:
            print(f"Error while removing default dataset 'ds' in Fuseki:\n{str(e)}")


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
    # check Fuseki triplestore for datasets
    tdb_ids_jena = None
    try:
        tdb_ids_jena = await FusekiConnection.get_all_tdb_ids(client)
    except Exception as e:
        print(f"\n####\nFuseki:\nERROR: {str(e)}\n####\n")

    # set variables for navbar
    name = request.session.get("name", "anonymous")
    email = request.session.get("email", "")
    api_key = request.session.get("api_key", "")
    role = request.session.get("role", [])

    ownurl = f"{request.url.scheme}://{request.url.hostname}"
    if request.url.port != 443 and request.url.port != 80:
        ownurl = f"{request.url.scheme}://{request.url.hostname}:{request.url.port}"
        

    if tdb_ids_jena and not any(x in role for x in settings.KEYCLOAK_ADMIN_ROLES):
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
                                                     "email": email,
                                                     "api_key": api_key,
                                                     "api_key_default_valid_days": settings.JWT_DEFAULT_DAYS_VALID,
                                                     "api_key_valid_to": decode_token(api_key).get("exp") if api_key else "-",
                                                     "ownurl": ownurl,
                                                     "property_tree": {},
                                                     "role": role,
                                                     "isAdminRole": any(x in role for x in settings.KEYCLOAK_ADMIN_ROLES),
                                                     "isReadWriteRole": any(x in role for x in settings.KEYCLOAK_READWRITE_ROLES),
                                                     "isReadOnlyRole": not role or any(x in role for x in settings.KEYCLOAK_READONLY_ROLES),
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

    name = request.session["name"]
    email = request.session["email"]
    role = request.session["role"]

    minDaysValid = int(os.environ.get("JWT_MIN_DAYS_VALID", 1))
    maxDaysValid = int(os.environ.get("JWT_MAX_DAYS_VALID", 90))
    if valid and valid.isdigit() and int(valid) >= minDaysValid and int(valid) <= maxDaysValid:
        # get user by query
        user = filter_users(email, db_session)
        
        api_key = create_apikey(name, email, role, int(valid), request, settings)
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

# This post request will reload the page
@app.post("/create_dataset",
          description="Create a new dataset in the Fuseki Jena triplestore. This endpoint requires authentication and the user must have the maintainer or admin role. The dataset is created by calling the `create_ds` method of the `FusekiConnection` class. If the dataset is successfully created, a success flash message is displayed. Otherwise, a warning flash message is displayed with the error message. After creating the dataset, the user is redirected to the homepage. If the `tdb_id` parameter is provided, the user is redirected to the corresponding dataset page. Otherwise, the user is redirected to the homepage.",
          summary="Create new dataset",
          tags=["Dataset"],
          dependencies=[Depends(check_auth), Depends(maintainer_or_admin_role)],
          include_in_schema=False  # hide this endpoint in Swagger UI (http://localhost/docs)
          )
async def create_dataset(response: Response, request: Request, create_tdb_id: Annotated[str, Form()],
                         settings: Annotated[Settings, Depends(get_settings)],
                         client: httpx.AsyncClient = Depends(get_client),
                         ):
    redirect_url = request.headers.get('Referer')  # get the url before redirection

    ownurl = f"{request.url.scheme}://{request.url.hostname}"
    if request.url.port != 443 and request.url.port != 80:
        ownurl = f"{request.url.scheme}://{request.url.hostname}:{request.url.port}"

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
    email = request.session.get("email", "")
    api_key = request.session.get("api_key", "")
    role = request.session.get("role", [])

    ownurl = f"{request.url.scheme}://{request.url.hostname}"
    if request.url.port != 443 and request.url.port != 80:
        ownurl = f"{request.url.scheme}://{request.url.hostname}:{request.url.port}"

    if tdb_ids_jena and not any(x in role for x in settings.KEYCLOAK_ADMIN_ROLES):
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
    
    r = await get_jenaconn(tdb_id).get_vowl(client)

    return templates.TemplateResponse("index.html", {"request": request,
                                                     "ds_isempty": ds_isempty,
                                                     "tdb_id": tdb_id,
                                                     "tdb_name": tdb_name,
                                                     "tdb_ids_jena": tdb_ids_jena,
                                                     "name": name,
                                                     "email": email,
                                                     "api_key": api_key,
                                                     "api_key_default_valid_days": settings.JWT_DEFAULT_DAYS_VALID,
                                                     "api_key_valid_to": decode_token(api_key).get("exp") if api_key else "-",
                                                     "ownurl": ownurl,
                                                     "role": role,
                                                     "named_graphs": named_graphs,
                                                     "isAdminRole": any(x in role for x in settings.KEYCLOAK_ADMIN_ROLES),
                                                     "isReadWriteRole": any(x in role for x in settings.KEYCLOAK_READWRITE_ROLES),
                                                     "isReadOnlyRole": not role or any(x in role for x in settings.KEYCLOAK_READONLY_ROLES)
                                                     })


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
          dependencies=[Depends(check_auth), Depends(maintainer_or_admin_role)],
          include_in_schema=False  # hide this endpoint in Swagger UI (http://localhost/docs)
          )
async def destroy_dataset(response: Response, request: Request, tdb_id: Annotated[str, Form()], tdb_name: str = "jena",
                          client: httpx.AsyncClient = Depends(get_client)):
    try:
        r = await get_jenaconn(tdb_id).destroy_ds(client)
        print(f"\n\n##########\n{r.status_code = }\n{str(r.content.decode('utf-8')) = }\n##########\n\n")
        if r.status_code == 200:
            flash(request,
                  message=f"Dataset <strong>{tdb_id}</strong> deleted",
                  category="success")
            tdb_id = tdb_name = ""  # set to empty string in order to get back to homepage
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

    print(f"\n####\n{redirect_url = }\n####\n")
    return RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)


@app.get('/jena/{tdb_id}/clear_cache',
         description="Clear cache of query results",
         summary="Clear cache of query results",
         tags=["Datasets"],
         dependencies=[Depends(check_auth), Depends(maintainer_or_admin_role)],
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
            oneRowDict["canDelete"] = one_row.user_id == request.session.get("id") or any(x in request.session.get("role", []) for x in settings.KEYCLOAK_ADMIN_ROLES)
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
            if(result.public or result.user_id == request.session.get("id") or any(x in request.session.get("role", []) for x in settings.KEYCLOAK_ADMIN_ROLES)):
                resultDict = result.__dict__
                resultDict.pop("_sa_instance_state")
                resultDict["canDelete"] = result.user_id == request.session.get("id") or any(x in request.session.get("role", []) for x in settings.KEYCLOAK_ADMIN_ROLES)
                return JSONResponse(content=resultDict, status_code=200)
        else:
            return JSONResponse(content=f"Query with ID {query_id} does not exist!", status_code=404)
    except Exception as e:
        print(f"Unexpected error: {e}")
        return JSONResponse(content=str(e), status_code=400)
    
@app.post("/saved_queries",
            dependencies=[Depends(check_auth), Depends(maintainer_or_admin_role)],
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
          dependencies=[Depends(check_auth), Depends(maintainer_or_admin_role)],
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
            if(result.user_id == request.session.get("id") or any(x in request.session.get("role", []) for x in settings.KEYCLOAK_ADMIN_ROLES)):
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
            dependencies=[Depends(check_auth), Depends(maintainer_or_admin_role)],
            include_in_schema=False)
async def delete_query(request: Request,
                       settings: Annotated[Settings, Depends(get_settings)],
                    db_session: Session = Depends(get_db_session)):
    try:
        query_id = request.path_params.get("query_id")
        result = find_sparql_query_by_id(query_id, db_session)
        if result:
            if(result.user_id == request.session.get("id") or any(x in request.session.get("role", []) for x in settings.KEYCLOAK_ADMIN_ROLES)):
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
          dependencies=[Depends(check_auth), Depends(maintainer_or_admin_role)],
          include_in_schema=False)  # use axios in frontend to prevent reload page
async def form_update(request: Request, role: Annotated[list, Depends(get_user_role)],
                      settings: Annotated[Settings, Depends(get_settings)],
                      update: Annotated[str, Form()],
                      tdb_id: str = Query("Tensile_Tests_Examples"),
                      client: httpx.AsyncClient = Depends(get_client)
                      ):
    if not request.session.get("name"):
        return JSONResponse(content="Not authenticated", status_code=401)

    if not role or (not any(x in role for x in settings.KEYCLOAK_ADMIN_ROLES) and not any(x in role for x in settings.KEYCLOAK_READWRITE_ROLES)):
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
        dependencies=[Depends(check_auth), Depends(admin_role)],
        include_in_schema=False)
async def admin_page(request: Request, 
                     settings: Annotated[Settings, Depends(get_settings)],
                     db_session: Session = Depends(get_db_session),
                     client: httpx.AsyncClient = Depends(get_client)):
    # Prepare Template for Admin Page
    pass

@app.get("/backup",
         description="Backup with all datasets data and saved queries.",
         dependencies=[Depends(check_auth), Depends(admin_role)],
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
        
@app.post("/restore",
            description="Restore from a previous backup with its data and saved queries.",
            dependencies=[Depends(check_auth), Depends(admin_role)],
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
          dependencies=[Depends(check_auth), Depends(maintainer_or_admin_role)],
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
         dependencies=[Depends(check_auth), Depends(admin_role)],
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
    email = request.session.get("email", "")
    api_key = request.session.get("api_key", "")
    role = request.session.get("role", [])
        

    if tdb_ids_jena and not any(x in role for x in settings.KEYCLOAK_ADMIN_ROLES):
        tdb_ids_jena = [item for item in tdb_ids_jena if
                        "-mem" not in item and
                        "_mem" not in item
                        ]

    return templates.TemplateResponse("admin_backup.html", {"request": request,
                                                     "name": name,
                                                     "email": email,
                                                     "tdb_ids_jena": tdb_ids_jena,
                                                     "api_key": api_key,
                                                     "api_key_default_valid_days": settings.JWT_DEFAULT_DAYS_VALID,
                                                     "api_key_valid_to": decode_token(api_key).get("exp") if api_key else "-",
                                                     "role": role,
                                                     "isAdminRole": any(x in role for x in settings.KEYCLOAK_ADMIN_ROLES),
                                                     "isReadWriteRole": any(x in role for x in settings.KEYCLOAK_READWRITE_ROLES),
                                                     "isReadOnlyRole": not role or any(x in role for x in settings.KEYCLOAK_READONLY_ROLES)
                                                     })

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
