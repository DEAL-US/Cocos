from django.test import SimpleTestCase
from rdflib import Graph

from semantics.model_page import model_page
from semantics.registry.descriptors import model_iri

MINIMAL = '''
@prefix schema: <https://schema.org/> .
<https://w3id.org/cocos/model/rules> a schema:SoftwareApplication ; schema:name "rules" .
'''


class ModelPageTests(SimpleTestCase):
    def test_a_model_that_declares_no_provenance_quality_or_files(self):
        page = model_page(Graph().parse(data=MINIMAL, format='turtle'), model_iri('rules'))
        self.assertEqual(page, {'built_from': [], 'metrics': [], 'antibiotics': [], 'files': []})
