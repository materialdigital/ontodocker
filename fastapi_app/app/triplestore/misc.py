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
