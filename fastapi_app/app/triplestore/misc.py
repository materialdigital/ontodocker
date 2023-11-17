"""
Copyright 2021, Leibniz-Institut für Werkstofforientierte Technologien - IWT.
All rights reserved.

 Redistribution and use in source and binary forms, with or without
 modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice,
   this list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its contributors
   may be used to endorse or promote products derived from this software
   without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

modified from https://git.material-digital.de/apps/ontodocker/-/blob/master/flask_app/app/triplestores/misc.py

"""
import os
import time


async def upload_onto(url, path_to_onto, client, headers):
    file_type = os.path.basename(path_to_onto).rsplit('.', 1)[1].lower()
    if file_type == "ttl":
        header = {"Content-Type": "text/turtle"}
    elif file_type == "rdf" or file_type == "owl":
        header = {"Content-Type": "application/rdf+xml"}

    # Combine headers
    combined_headers = header.copy()  # Create a copy of the first header
    combined_headers.update(headers)  # Update with the contents of the second header

    with open(path_to_onto, 'rb') as file:
        data = file.read()
    start_time = time.time()  # Record the start time
    r = await client.post(url, headers=combined_headers, content=data)
    end_time = time.time()  # Record the end time
    elapsed_time = end_time - start_time  # Calculate the elapsed time
    print(f"\n#####\nElapsed time: {elapsed_time} seconds\n#####\n")
    print(f"{os.path.basename(path_to_onto) = } {r.status_code = } {r.content = }")
    return r
