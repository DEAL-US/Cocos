import os
import requests

BASE = os.getenv("ANNOTATION_BASE", "http://localhost:8000")

if os.getenv("MOCK", "false").lower() == "true":
    BASE = os.getenv("MOCK_ANNOTATION_BASE", "http://localhost:8000")

def get_job_status(job_id):
    response = requests.get(f"{BASE}/jobs/{job_id}")
    if response.status_code == 404:
        return None, 404
    response.raise_for_status()
    status = response.json()["status"]
    return status, response.status_code

def sequence_illumina(fastq_content, fastq_2_content, annotate=False):
    resp = requests.post(
        f"{BASE}/assembly/illumina?annotate=" + str(annotate).lower(),
        files={
            "r1": ("r1", fastq_content, "application/gzip"),
            "r2": ("r2", fastq_2_content, "application/gzip"),
        },
        timeout=60,
    )
    if resp.status_code == 503:
        print("Received 503 Server Busy response")
        return resp.json()
    resp.raise_for_status()
    return resp.json()

def sequence_ont(fastq_content, annotate=False):
    try:
        resp = requests.post(
            f"{BASE}/assembly/ont?annotate=" + str(annotate).lower(),
            files={"reads": ("reads", fastq_content, "application/gzip")},
            timeout=300,
        )
    except requests.exceptions.ReadTimeout:
        print("ReadTimeout when contacting bio-assembly-api for ONT assembly")
        return {"status": "busy"}
    except requests.exceptions.RequestException as e:
        print("Request error when contacting bio-assembly-api for ONT assembly:", str(e))
        raise
    if resp.status_code == 503:
        print("Received 503 Server Busy response")
        return resp.json()
    resp.raise_for_status()
    return resp.json()

def perform_bakta_annotation_from_job(job_id):
    response = requests.post(f"{BASE}/annotation/bakta/existing/{job_id}?threads=4")
    response.raise_for_status()
    return response.json()

def annotate_from_fasta(fasta_content, threads=4):
    resp = requests.post(
        f"{BASE}/annotation/bakta/upload?threads={threads}",
        files={"assembly": ("sequences.fasta", fasta_content, "application/octet-stream")},
        timeout=30,
    )
    if resp.status_code == 503:
        print("Received 503 Server Busy response")
        return resp.json()
    resp.raise_for_status()
    return resp.json()

def download_bakta_json_result(job_id):
    response = requests.get(f"{BASE}/annotation/{job_id}/download?format=json")
    response.raise_for_status()
    return response.json()

def download_assembly_fasta_result(job_id):
    response = requests.get(f"{BASE}/assembly/{job_id}/download")
    response.raise_for_status()
    return response.content