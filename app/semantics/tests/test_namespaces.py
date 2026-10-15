from django.test import SimpleTestCase
from rdflib import Graph

from semantics.namespaces import AMRF, EDAM, OBO, bind_prefixes


class BindPrefixesTests(SimpleTestCase):
    def test_serialized_graph_uses_the_cocos_prefixes(self):
        graph = bind_prefixes(Graph())
        graph.add((AMRF.example, EDAM.has_format, OBO.ARO_0000073))

        turtle = graph.serialize(format='turtle')

        self.assertIn('@prefix amrf: <https://w3id.org/amrf/> .', turtle)
        self.assertIn('amrf:example edam:has_format obo:ARO_0000073', turtle)
