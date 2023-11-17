import asyncio
import os
import time
from json import JSONDecodeError
import httpx
from typing import Annotated

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

from werkzeug.utils import secure_filename

# TODO I can't use from . import XXX (ImportError: attempted relative import with no known parent package)
from __init__ import create_db_and_tables
from __init__ import templates

from config import Data, get_data

from utils import flash, extract_queryresults, is_file_allowed
from triplestore.jena import get_jenaconn, FusekiConnection
from routers import auth, api, project
from doc import description

from dependencies import get_client, verify_token, check_auth, get_user_role, admin_role

from cachetools import LFUCache

cache = LFUCache(maxsize=500)

app = FastAPI(title="Fast Ontodocker App", version="0.2.0", description=description)

app.add_middleware(SessionMiddleware, max_age=14 * 24 * 60 * 60,
                   secret_key="8fe799597d4cdf3ada601dcc69d0d3193a9f6cff66849ddf4e357f1d667e7b07")
# secret generated by openssl rand -hex 32
# max_age is by default set to 14 days, this should be less than the "SSO
# Session Idle" time in the Keycloak settings. so that if the session expires after the desired time, the user will
# be redirected to the Keycloak login page
app.add_middleware(GZipMiddleware)  # Defaults to 500 bytes

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Replace with your desired origin
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, tags=["Authentication"])
app.include_router(project.router, tags=["Project portal"],
                   dependencies=[Depends(check_auth)]
                   )

app.include_router(api.router,
                   prefix="/api/v1",
                   tags=["APIs"],
                   dependencies=[Depends(verify_token)])


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
         dependencies=[Depends(check_auth)],
         include_in_schema=False  # hide this endpoint in Swagger UI (http://localhost/docs)
         )
async def homepage(response: Response, request: Request,
                   client: httpx.AsyncClient = Depends(get_client)):
    # check Fuseki triplestore for datasets
    tdb_ids_jena = None
    try:
        tdb_ids_jena = await FusekiConnection.get_all_tdb_ids(client)
    except Exception as e:
        print(f"\n####\nFuseki:\nERROR: {str(e)}\n####\n")

    # set variables for navbar
    name = request.session.get("name")
    email = request.session.get("email")
    api_key = request.session.get("api_key")
    role = request.session.get("role")

    ownurl = "http://localhost"

    if tdb_ids_jena and "admin" not in role and "App-admin" not in role:
        tdb_ids_jena = [item for item in tdb_ids_jena if
                        "test" not in item and
                        "debug" not in item and
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
                                                     "ownurl": ownurl,
                                                     "property_tree": {},
                                                     "role": role
                                                     })


# This post request will reload the page
@app.post("/create_dataset",
          description="Create new dataset.",
          summary="Create new dataset",
          tags=["Dataset"],
          dependencies=[Depends(check_auth), Depends(admin_role)],
          include_in_schema=False  # hide this endpoint in Swagger UI (http://localhost/docs)
          )
async def create_dataset(response: Response, request: Request, create_tdb_id: Annotated[str, Form()],
                         client: httpx.AsyncClient = Depends(get_client),
                         ):
    redirect_url = request.headers.get('Referer')  # get the url before redirection

    ownurl = f"http://localhost"

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
         description="Query UI page.<br>"
                     "Visit <a href='/'>Homepage</a>.",
         summary="Query UI page",
         tags=["Datasets"],
         dependencies=[Depends(check_auth)],
         include_in_schema=False  # hide this endpoint in Swagger UI (http://localhost/docs)
         )
async def datasets(response: Response, request: Request, tdb_id: str = "", tdb_name: str = "jena",
                   client: httpx.AsyncClient = Depends(get_client),
                   dict_data: Data = Depends(get_data)):
    tdb_ids_jena = []
    tdb_ids_jena = await FusekiConnection.get_all_tdb_ids(client)
    print(f"\n####\nFuseki:\n{tdb_ids_jena = }\n####\n")
    if tdb_ids_jena is None:
        raise HTTPException(status_code=503, detail="Triplestore unavailable")

    # set variables for navbar
    name = request.session.get("name")
    email = request.session.get("email")
    api_key = request.session.get("api_key")
    role = request.session.get("role")

    ownurl = "http://localhost"

    if tdb_ids_jena and "admin" not in role and "App-admin" not in role:
        tdb_ids_jena = [item for item in tdb_ids_jena if
                        "test" not in item and
                        "debug" not in item and
                        "-mem" not in item and
                        "_mem" not in item
                        ]

    if tdb_name == "jena":
        if tdb_id not in tdb_ids_jena:
            raise HTTPException(status_code=404, detail="dataset name not found")
    else:
        raise HTTPException(status_code=404, detail="Triplestore not exist")

    property_tree = dict_data.property_data

    return templates.TemplateResponse("index.html", {"request": request,
                                                     "tdb_id": tdb_id,
                                                     "tdb_name": tdb_name,
                                                     "tdb_ids_jena": tdb_ids_jena,
                                                     "name": name,
                                                     "email": email,
                                                     "api_key": api_key,
                                                     "ownurl": ownurl,
                                                     "property_tree": property_tree,
                                                     "role": role,
                                                     })


# This post request will reload the page
# Other post requests like query, update, and upload
# are handled in the individual endpoints below with axios in frontend to prevent page reloads
@app.post('/destroy_dataset',
          description="Destroy dataset.<br>",
          summary="Destroy dataset",
          tags=["Datasets"],
          dependencies=[Depends(check_auth), Depends(admin_role)],
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
         dependencies=[Depends(admin_role)],
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


@app.post("/query",
          description="Query data in dataset.",
          summary="Query data in dataset",
          tags=["SPARQL"])  # use axios in frontend to prevent reload page
async def form_query(request: Request, tdb_id: str = Query("SciGlass"),
                     query: str = Form("SELECT * WHERE {?sub ?pred ?obj .} LIMIT 10"),
                     client: httpx.AsyncClient = Depends(get_client),
                     is_cache: bool = True):
    if not request.session.get("name"):
        return JSONResponse(content="Not authenticated", status_code=401)

    try:
        # Check if the result is already in the cache. If you don't want a cache, set is_cache to False (in frontend or backend)
        if is_cache:
            result = cache.get(tdb_id + query)
            if result is not None:
                print(f"Found query result in cache")
                return result

        r = await get_jenaconn(tdb_id).query(query, client)

        if r.status_code == 200:
            head, data = extract_queryresults(r.json())

            data = {
                "head": [{"title": column} for column in head],
                "data": data
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
        print(f"\n###QUERY_TIMEOUT\n###\n")
        return JSONResponse(content="Query timeout (60s)",
                            status_code=400)  # see QUERY_TIMEOUT argument in docker-compose.yml

    except Exception as e:
        print(f"\n###\nUnexpected error: \n{e = }\n###\n")
        return JSONResponse(content=str(e), status_code=400)


@app.post("/update",
          description="Update data in dataset.",
          summary="Update data in dataset",
          tags=["SPARQL"])  # use axios in frontend to prevent reload page
async def form_update(request: Request, role: Annotated[list, Depends(get_user_role)],
                      update: Annotated[str, Form()],
                      tdb_id: str = Query("SciGlass"),
                      client: httpx.AsyncClient = Depends(get_client)
                      ):
    if not request.session.get("name"):
        return JSONResponse(content="Not authenticated", status_code=401)

    if "admin" not in role and "App-admin" not in role:
        return JSONResponse(content="Access forbidden (admin only for now)", status_code=403)

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

# TODO in the future version the function "/upload" will be integrated into the endpoint "/pipeline"
@app.post("/upload",
          description="Upload RDF data (.rdf or .ttl) to Fuseki Jena dataset.",
          summary="Upload RDF data (.rdf or .ttl) to Fuseki Jena dataset",
          tags=["SPARQL"])  # use axios in frontend to prevent reload page
async def upload_file(request: Request, role: Annotated[list, Depends(get_user_role)],
                      tdb_name: str = "jena", tdb_id: str = Query(), file: UploadFile = File(...),
                      client: httpx.AsyncClient = Depends(get_client)
                      ):
    if not request.session.get("name"):
        return JSONResponse(content="Not authenticated", status_code=401)

    if "admin" not in role and "App-admin" not in role:
        return JSONResponse(content="Access forbidden (admin only for now)", status_code=403)

    # print(f"\n#####\nUploading files...\n#####\n")

    try:

        # Frontend checked, but check again in backend in case someone bypasses it via script upload
        if not is_file_allowed(file.filename):
            return JSONResponse("Not a file or filetype not allowed", status_code=422)

        # TODO I have not checked the file size here in the backend, but only in the frontend, which is not so safe

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
            r = await get_jenaconn(tdb_id).upload(filepath, client)
            if r.status_code == 200:
                # Clear the cache
                cache.clear()

            return JSONResponse(content=r.content.decode("utf-8"), status_code=r.status_code)

        else:
            raise HTTPException(status_code=404, detail="Triplestore not exist")

    except Exception as e:
        print(f'{e = }')
        return JSONResponse(content=str(e), status_code=400)


@app.exception_handler(401)
async def custom_401_handler(request: Request, __):
    return templates.TemplateResponse("401.html", {"request": request}, status_code=status.HTTP_401_UNAUTHORIZED)


@app.exception_handler(403)
async def custom_403_handler(request: Request, __):
    return templates.TemplateResponse("403.html", {"request": request}, status_code=status.HTTP_403_FORBIDDEN)


@app.exception_handler(404)
async def custom_404_handler(request: Request, __):
    return templates.TemplateResponse("404.html", {"request": request}, status_code=status.HTTP_404_NOT_FOUND)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return templates.TemplateResponse("422.html", {"request": request, "error": jsonable_encoder(
        {"detail": exc.errors(), "body": exc.body})}, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)


@app.exception_handler(500)
async def custom_500_handler(request: Request, __):
    return templates.TemplateResponse("500.html", {"request": request}, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@app.exception_handler(503)
async def custom_503_handler(request: Request, __):
    return templates.TemplateResponse("503.html", {"request": request}, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)


@app.exception_handler(504)
async def custom_504_handler(request: Request, __):
    return templates.TemplateResponse("504.html", {"request": request}, status_code=status.HTTP_504_GATEWAY_TIMEOUT)
