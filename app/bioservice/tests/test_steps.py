from unittest.mock import patch

import requests
from django.core.cache import cache
from django.test import SimpleTestCase

from bioservice.steps import TOOLS_CACHE_KEY, installed_tools

TOOLS = {'assembly': {'ont': [{'name': 'Raven', 'version': '1.8.3', 'type': 'tool'}]}, 'annotation': []}


class InstalledToolsTests(SimpleTestCase):
    def setUp(self):
        cache.delete(TOOLS_CACHE_KEY)
        self.addCleanup(cache.delete, TOOLS_CACHE_KEY)

    def test_the_bio_service_is_asked_once_and_the_answer_is_kept(self):
        with patch('bioservice.client.get_tools', return_value=TOOLS) as get_tools:
            self.assertEqual(installed_tools(), TOOLS)
            self.assertEqual(installed_tools(), TOOLS)
        self.assertEqual(get_tools.call_count, 1)

    def test_without_an_answer_the_tools_are_unknown(self):
        with patch('bioservice.client.get_tools', side_effect=requests.ConnectionError) as get_tools:
            self.assertIsNone(installed_tools())
            self.assertIsNone(installed_tools())  # the failure is kept for a while too
        self.assertEqual(get_tools.call_count, 1)
