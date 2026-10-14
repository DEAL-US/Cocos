from unittest.mock import MagicMock, patch
import requests
from django.test import TestCase

from conversion.bio_api_client import (
    annotate_from_fasta,
    download_assembly_fasta_result,
    download_bakta_json_result,
    get_job_status,
    sequence_illumina,
    sequence_ont,
)

class BioApiClientTests(TestCase):
    @patch("conversion.bio_api_client.requests.get")
    def test_get_job_status_success(self, mock_get):
        response = MagicMock(status_code=200)
        response.json.return_value = {"status": "running"}
        mock_get.return_value = response
        self.assertEqual(get_job_status("job-1"), ("running", 200))

    @patch("conversion.bio_api_client.requests.get")
    def test_get_job_status_missing_job_returns_404_without_raising(self, mock_get):
        mock_get.return_value = MagicMock(status_code=404)
        self.assertEqual(get_job_status("job-1"), (None, 404))

    @patch("conversion.bio_api_client.requests.get")
    def test_download_bakta_json_result_success(self, mock_get):
        response = MagicMock(status_code=200)
        response.json.return_value = {"features": []}
        mock_get.return_value = response
        out = download_bakta_json_result("job-1")
        self.assertEqual(out["features"], [])

    @patch("conversion.bio_api_client.requests.get")
    def test_download_assembly_fasta_success(self, mock_get):
        response = MagicMock(status_code=200)
        response.content = b">x\nATG\n"
        mock_get.return_value = response
        self.assertEqual(download_assembly_fasta_result("job-1"), b">x\nATG\n")

    @patch("conversion.bio_api_client.requests.post")
    def test_annotate_from_fasta_success(self, mock_post):
        response = MagicMock(status_code=200)
        response.json.return_value = {"job_id": "a1", "status": "running"}
        mock_post.return_value = response
        out = annotate_from_fasta(b"fasta")
        self.assertEqual(out["job_id"], "a1")
        self.assertEqual(out["status"], "running")

    @patch("conversion.bio_api_client.requests.post")
    def test_sequence_illumina_success(self, mock_post):
        response = MagicMock(status_code=200)
        response.json.return_value = {"job_id": "s1", "status": "running"}
        mock_post.return_value = response
        out = sequence_illumina(b"r1", b"r2")
        self.assertEqual(out["job_id"], "s1")
        self.assertEqual(out["status"], "running")

    @patch("conversion.bio_api_client.requests.post")
    def test_sequence_ont_success(self, mock_post):
        response = MagicMock(status_code=200)
        response.json.return_value = {"job_id": "s2", "status": "running"}
        mock_post.return_value = response
        out = sequence_ont(b"reads")
        self.assertEqual(out["job_id"], "s2")
        self.assertEqual(out["status"], "running")

    def test_raise_http_error(self):
        cases = [
            (get_job_status, "get", ("job-1",)),
            (download_bakta_json_result, "get", ("job-1",)),
            (download_assembly_fasta_result, "get", ("job-1",)),
        ]
        for function, method, args in cases:
            with self.subTest(fn=function.__name__):
                with patch(f"conversion.bio_api_client.requests.{method}") as mock_req:
                    response = MagicMock(status_code=500)
                    response.raise_for_status.side_effect = requests.exceptions.HTTPError("boom")
                    mock_req.return_value = response
                    with self.assertRaises(requests.exceptions.HTTPError):
                        function(*args)

    def test_busy_503_returns_json(self):
        cases = [
            (annotate_from_fasta, (b"fasta",)),
            (sequence_illumina, (b"r1", b"r2")),
            (sequence_ont, (b"reads",)),
        ]
        for function, args in cases:
            with self.subTest(fn=function.__name__):
                with patch("conversion.bio_api_client.requests.post") as mock_post:
                    response = MagicMock(status_code=503)
                    response.json.return_value = {"status": "busy"}
                    mock_post.return_value = response
                    self.assertEqual(function(*args)["status"], "busy")

    @patch("conversion.bio_api_client.requests.post")
    def test_sequence_ont_timeout_returns_busy_status(self, mock_post):
        mock_post.side_effect = requests.exceptions.ReadTimeout()
        self.assertEqual(sequence_ont(b"reads")["status"], "busy")

    @patch("conversion.bio_api_client.requests.post")
    def test_sequence_ont_request_exception_is_raised(self, mock_post):
        mock_post.side_effect = requests.exceptions.RequestException("connection")
        with self.assertRaises(requests.exceptions.RequestException):
            sequence_ont(b"reads")
