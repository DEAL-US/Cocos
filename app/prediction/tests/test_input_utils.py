import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings

from core.models import FileGene, Gene
from core.models import File
from prediction.adapters import input_utils

User = get_user_model()


class PresenceFromListTests(TestCase):
    def setUp(self):
        self.media_dir = tempfile.mkdtemp()
        media_override = override_settings(MEDIA_ROOT=self.media_dir)
        media_override.enable()
        self.addCleanup(media_override.disable)
        self.addCleanup(shutil.rmtree, self.media_dir, ignore_errors=True)

        self.user = User.objects.create_user(username="pred_user", password="pass1234")
        self.file_upload = File.objects.create(
            user=self.user,
            file=ContentFile(b"{}", name="sample.json"),
            file_type='json'
        )

        gene_a = Gene.objects.create(identifiers=" UniRef:UniRef50_AAA , UniRef:UniRef50_BBB ")
        gene_b = Gene.objects.create(identifiers="UniRef:UniRef50_ccc,uniref:uniref50_ddd")

        FileGene.objects.create(file=self.file_upload, gene=gene_a, expert="test")
        FileGene.objects.create(file=self.file_upload, gene=gene_b, expert="test")

    def test_presence_from_list_matches_normalized_identifiers(self):
        model_features = [
            "uniref:uniref50_aaa",
            "UniRef:UniRef50_BBB",
            "uniref:uniref50_ddd",
            "uniref:uniref50_missing",
        ]
        out = input_utils.presence_from_list(model_features, self.file_upload)
        self.assertEqual(out, [1, 1, 1, 0])

    def test_presence_from_list_returns_zeros_without_genes_relation(self):
        model_features = ["a", "b", "c"]
        out = input_utils.presence_from_list(model_features, object())
        self.assertEqual(out, [0, 0, 0])

    def test_presence_from_list_handles_empty_features(self):
        self.assertEqual(input_utils.presence_from_list([], self.file_upload), [])


class InputFileLoadingTests(TestCase):
    model_name = "base_bakta_50"

    def test_get_columns_from_pickle_returns_columns(self):
        cols = input_utils.get_columns_from_pickle(self.model_name, "columns.pkl")
        self.assertIsInstance(cols, list)
        self.assertGreater(len(cols), 0)
        self.assertTrue(all(isinstance(col, str) for col in cols))

    def test_get_model_weights_path_returns_existing_file_path(self):
        out = input_utils.get_model_weights_path("amikacin", self.model_name)
        self.assertTrue(out.endswith("amikacin.pt"))

    def test_get_model_weights_path_raises_when_missing(self):
        with self.assertRaises(FileNotFoundError):
            input_utils.get_model_weights_path("nonexistent", self.model_name)
