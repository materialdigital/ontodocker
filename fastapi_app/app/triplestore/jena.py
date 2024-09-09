import base64
import json
import shutil

import os
import sys
from functools import lru_cache
from typing import Optional, List
import jpype

import requests
from fastapi.responses import JSONResponse

from pydantic import BaseSettings
from .misc import upload_onto_str

sys.path.append("..")  # Adds higher directory to python modules path.
from config import FusekiSettings, get_fuseki_settings
from utils import extract_queryresults

filename = os.path.basename(__file__)
filedir = os.path.dirname(os.path.realpath(__file__)) + "/"
var_dir = filedir + "var/"


class FusekiConnection():
    _url = f'http://fuseki:3030'

    # this is Fuseki UI admin credentials, required when using secoresearch/fuseki
    credentials = get_fuseki_settings().credentials
    encoded_credentials = base64.b64encode(credentials.encode('utf-8')).decode('utf-8')
    # print(f"{credentials.encode('utf-8') = }")
    # print(f"{base64.b64encode(credentials.encode('utf-8')) = }")
    # print(f"{encoded_credentials = }")
    _header = {"Authorization": f"Basic {encoded_credentials}"}

    def __init__(self, tdb_id):
        self.tdb_id = tdb_id
        self.endpoint = f'{self._url}/{tdb_id}'
        self.server = f'{self.endpoint}/sparql'
        # TODO Note: default dataset "ds" of secoresearch/fuseki, doesn't contain "/query" endpoint
        self.upserver = f'{self.endpoint}/update'

    @staticmethod
    async def get_server_status(client):
        return await client.get(f'{FusekiConnection._url}/$/server', headers=FusekiConnection._header)


    @staticmethod
    async def get_all_tdb_ids(client):
        r = await client.get(f'{FusekiConnection._url}/$/server', headers=FusekiConnection._header)
        # print(f"{r.status_code = }")
        if r.status_code == 200:
            rcontent = str(r.content.decode("utf-8"))
            lst = json.loads(rcontent).get("datasets", {})
            tbds = []
            for l in lst:
                tbds.append(
                    l["ds.name"][1:] if l["ds.name"][0] == "/" else l["ds.name"]
                )  # cut of leading backslash

            return tbds
        else:
            # print(f"\n###{r.text = }\n###\n")
            # print(f"\n###{r.content.decode('utf-8') = }\n###\n")
            return None

    async def create_ds(self, client):
        # https://stackoverflow.com/q/42421915
        return await client.post(f'{self._url}/$/datasets', params={"dbName": self.tdb_id, "dbType": "tdb2"},
                                 headers=FusekiConnection._header)

    async def destroy_ds(self, client):
        return await client.delete(f'{self._url}/$/datasets/{self.tdb_id}', headers=FusekiConnection._header)

    async def query(self, query, client):
        return await client.get(self.server, params={"query": query}, headers=FusekiConnection._header)

    async def update(self, update_query, client):
        return await client.post(self.upserver, data={"update": update_query}, headers=FusekiConnection._header)

    async def upload(self, path_to_onto, named_graph, client):
        print(f"\n####\n{path_to_onto = }\n####\n")
        
        file_type = os.path.basename(path_to_onto).rsplit('.', 1)[1].lower()
    
        with open(path_to_onto, 'rb') as file:
            data = file.read()

        url = f'{self.endpoint}/data?graph={named_graph}'
        if file_type.lower() == "trig":
            # Trig Files contain graph information inside, so no specification in URI
            url = f'{self.endpoint}/data'
            
        return await upload_onto_str(url, data, client, FusekiConnection._header, file_type)
        
    async def get_namedgraphs(self, client):
        query = "SELECT ?g WHERE { GRAPH ?g { } }"
        r = await client.post(self.server, params={"query": query}, headers=FusekiConnection._header)
        head, data, raw = extract_queryresults(r)
        if data is None or len(data) == 0:
            return None
        return [named_graph[0] for named_graph in data]
    
    async def data(self, client):
        url = f'{self.endpoint}/data'
        r = await client.get(url, headers=FusekiConnection._header)
        return r
    
    async def upload_data(self, onto_str, client, data_type = "trig"):
        url = f'{self.endpoint}/data'
        return await upload_onto_str(url, onto_str, client, FusekiConnection._header, data_type)

    async def get_vowl(self, client):
        url = f'{self.endpoint}/data?default'
        r = await client.get(url, headers=FusekiConnection._header)
        # get graph
        to_convert = f"{var_dir}jena_all.rdf"
        with open(to_convert, "bw") as f:
            f.write(r.content)

        # convert to vowl
        tmp = f"{var_dir}{self.tdb_id}.json"
        jpype.JPackage('de').uni_stuttgart.vis.vowl.owl2vowl.ConsoleMain.main(["-file", to_convert, "-output", tmp])


        # copy to webvwol
        shutil.copy(tmp, f"{filedir}/../static/vowl/data/{self.tdb_id}.json")

        # delete tmp files
        os.remove(to_convert)
        os.remove(tmp)



def get_jenaconn(tdb_id):
    return FusekiConnection(tdb_id)


class FusekiDataset(BaseSettings):
    tbds: Optional[List[str]] = None


@lru_cache()
def get_fusekidataset():
    return FusekiDataset()
