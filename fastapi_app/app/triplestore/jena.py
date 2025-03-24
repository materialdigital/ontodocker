import base64
import json
import shutil

import os
import sys
from functools import lru_cache
from typing import Optional, List
import jpype
import hashlib
import subprocess
import docker

from rdflib import Graph, Namespace, URIRef, BNode
from rdflib.namespace import RDF, RDFS

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

reasoner_urls = {
    "TransitiveReasoner": "http://jena.hpl.hp.com/2003/TransitiveReasoner",
    "RDFSExptRuleReasoner": "http://jena.hpl.hp.com/2003/RDFSExptRuleReasoner",
    "OWLFBRuleReasoner": "http://jena.hpl.hp.com/2003/OWLFBRuleReasoner",
    "OWLMiniFBRuleReasoner": "http://jena.hpl.hp.com/2003/OWLMiniFBRuleReasoner",
    "OWLMicroFBRuleReasoner": "http://jena.hpl.hp.com/2003/OWLMicroFBRuleReasoner"
}

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
                tdb_name = l["ds.name"][1:] if l["ds.name"][0] == "/" else l["ds.name"]
                if tdb_name != "ds":
                    tbds.append(tdb_name)  # cut of leading backslash
            return tbds
        else:
            # print(f"\n###{r.text = }\n###\n")
            # print(f"\n###{r.content.decode('utf-8') = }\n###\n")
            return None

    async def create_ds(self, client):
        await self.set_reasoner("test2", "http://jena.hpl.hp.com/2003/OWLMiniFBRuleReasoner")
        # await self.set_reasoner("test2", "")
        # https://stackoverflow.com/q/42421915
        return await client.post(f'{self._url}/$/datasets', params={"dbName": self.tdb_id, "dbType": "tdb2"},
                                 headers=FusekiConnection._header)
    
    async def get_reasoner(self, tdb_id):
        # Load the existing TTL file
        g = Graph()
        g.parse(f"/data/fuseki/configuration/{tdb_id}.ttl", format="turtle")

        # Define namespaces
        base = Namespace("http://base/#")
        ja = Namespace("http://jena.hpl.hp.com/2005/11/Assembler#")

        # Find the blank node used in the `ja:reasoner` property
        for s, p, o in g.triples((base.model_inf, ja.reasoner, None)):
            if isinstance(o, BNode):
                for s2, p2, o2 in g.triples((o, ja.reasonerURL, None)):
                    reasoner_url = str(o2)
                    reasoner = [key for key, value in reasoner_urls.items() if value == reasoner_url]
                    if len(reasoner) > 0:
                        return reasoner[0]
                    return str(o2)
        return None
    
    async def set_reasoner(self, tdb_id, reasoner):

        if reasoner not in reasoner_urls and reasoner != "":
            return JSONResponse(content="Invalid reasoner", status_code=400)
        
        if reasoner == "":
            reasoner_url = None
        else:
            reasoner_url = reasoner_urls[reasoner]

        # Load the existing TTL file
        g = Graph()
        g.parse(f"/data/fuseki/configuration/{tdb_id}.ttl", format="turtle")

        # Define namespaces
        base = Namespace("http://base/#")
        fuseki = Namespace("http://jena.apache.org/fuseki#")
        ja = Namespace("http://jena.hpl.hp.com/2005/11/Assembler#")
        tdb2 = Namespace("http://jena.apache.org/2016/tdb#")

        # Revert the dataset for :service_tdb_all
        g.set((base.service_tdb_all, fuseki.dataset, base.tdb_dataset_readwrite))

        # Find the blank node used in the `ja:reasoner` property
        for s, p, o in g.triples((base.model_inf, ja.reasoner, None)):
            if isinstance(o, BNode):  # Check if the object is a blank node
                g.remove((o, None, None))
                break

        # Remove the added triples
        g.remove((base.inf_dataset, None, None))
        g.remove((base.model_inf, None, None))
        g.remove((base.tdbGraph, None, None))

        if reasoner_url:
            # Update the dataset for :service_tdb_all
            g.set((base.service_tdb_all, fuseki.dataset, base.inf_dataset))

            # Add new triples
            g.add((base.inf_dataset, RDF.type, ja.RDFDataset))
            g.add((base.inf_dataset, ja.defaultGraph, base.model_inf))

            reasoner_blank_node = BNode()
            g.add((base.model_inf, RDF.type, ja.InfModel))
            g.add((base.model_inf, ja.baseModel, base.tdbGraph))
            g.add((base.model_inf, ja.reasoner, reasoner_blank_node))
            g.add((reasoner_blank_node, ja.reasonerURL, URIRef(reasoner_url)))

            g.add((base.tdbGraph, RDF.type, tdb2.GraphTDB))
            g.add((base.tdbGraph, tdb2.dataset, base.tdb_dataset_readwrite))

        # Save the updated graph back to the file
        g.serialize(destination=f"/data/fuseki/configuration/{tdb_id}.ttl", format="turtle")

        # Restart Fuseki
        self.restart_fuseki_container()
        return JSONResponse(content="Reasoner set, Fuseki restarting", status_code=200)

    @staticmethod
    def restart_fuseki_container():
        container_name = "fuseki"
        # Docker-Client initialisieren
        client = docker.from_env()

        try:
            # Container anhand des Namens finden
            container = client.containers.get(container_name)

            # Container neu starten
            container.restart()
            print(f"Container '{container_name}' wurde erfolgreich neu gestartet.")
        except docker.errors.NotFound:
            print(f"Container '{container_name}' wurde nicht gefunden.")
        except docker.errors.APIError as e:
            print(f"Fehler beim Neustarten des Containers: {e}")

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
