from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.test import TestCase
from core.models import FileGene, Gene
from core.models import File
from conversion.parsers import PARSERS, get_parser, parse_file, register_parser
from parsers.bakta_json.parser import BaktaJsonParser
from pathlib import Path
import json

User = get_user_model()

class ParserRegistryTests(TestCase):
    def test_registered_and_unknown_parser_lookup(self):
        cases = [
            ("bakta_json", True),
            ("unknown_parser", False),
        ]
        for parser_name, should_exist in cases:
            with self.subTest(parser_name=parser_name):
                parser = get_parser(parser_name)
                if should_exist:
                    self.assertIsNotNone(parser)
                    self.assertTrue(hasattr(parser, "parse"))
                else:
                    self.assertIsNone(parser)

    def test_register_and_parse_dispatch(self):
        
        self.addCleanup(PARSERS.pop, "dummy_parser_test", None)

        @register_parser("dummy_parser_test")
        class DummyParser:
            def parse(self, data, file, user=None, options=None):
                return {"ok": True, "data": data, "file_name": file.name, "user": user}

        out = parse_file("dummy_parser_test", {"x": 1}, ContentFile(b"", name="x.dat"), user="u")
        self.assertEqual(out["ok"], True)
        self.assertEqual(out["data"], {"x": 1})
        self.assertEqual(out["file_name"], "x.dat")
        self.assertEqual(out["user"], "u")

    def test_parse_file_raises_for_unknown_parser(self):
        with self.assertRaises(RuntimeError):
            parse_file("not_registered", {}, ContentFile(b"", name="x.json"), user=None)


class BaktaJsonParserTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="pass1234")
        self.parser = BaktaJsonParser()
        self.fixture_path = Path(__file__).parent / "fixtures" / "small.json"

    def _json_file(self):
        return File.objects.create(user=self.user, file_type=File.FileType.JSON)

    def _load_small_payload(self):
        return json.loads(self.fixture_path.read_text(encoding="utf-8"))

    def test_correct_parsing(self):
        payload = self._load_small_payload()
        feature = payload["features"][0]
        single_feature_payload = {"features": [feature]}
        cases = [
            ({"complete_version": False}, None, None, None, None),
            (
                {"complete_version": True},
                feature["start"],
                feature["stop"],
                feature["nt"],
                feature["aa"],
            ),
        ]
        for options, expected_start, expected_stop, expected_nt, expected_aa in cases:
            with self.subTest(options=options):
                upload = self.parser.parse(
                    single_feature_payload,
                    self._json_file(),
                    user=self.user,
                    options=options,
                )
                self.assertIsInstance(upload, File)
                self.assertEqual(upload.genes.count(), 1)
                gene = upload.genes.first()
                for expected_identifier in [feature["gene"], feature["product"], feature["db_xrefs"][0]]:
                    self.assertIn(expected_identifier, gene.identifiers_list())
                file_gene = FileGene.objects.filter(file=upload).first()
                self.assertEqual(file_gene.expert, feature["expert"][0]["type"])
                self.assertEqual(file_gene.start, expected_start)
                self.assertEqual(file_gene.stop, expected_stop)
                self.assertEqual(file_gene.nt, expected_nt)
                self.assertEqual(file_gene.aa, expected_aa)

    def test_parse_reuses_existing_gene(self):
        payload = self._load_small_payload()
        payload["features"][0]["product"] = "new alias"
        existing = Gene.objects.create(identifiers=payload["features"][0]["gene"])
        upload = self.parser.parse(
            payload,
            self._json_file(),
            user=self.user,
        )
        self.assertIn(existing.id, upload.genes.values_list("id", flat=True))
        self.assertIn("new alias", existing.__class__.objects.get(id=existing.id).identifiers_list())

    def test_file_gene_requires_json_file(self):
        fasta_file = File.objects.create(user=self.user, file_type=File.FileType.FASTA)
        gene = Gene.objects.create(identifiers='gatA')

        file_gene = FileGene(file=fasta_file, gene=gene, expert='expert')

        with self.assertRaises(ValidationError):
            file_gene.save()
