from django.test import SimpleTestCase
from rdflib import Literal, URIRef
from rdflib.namespace import DCTERMS, RDF

from core.steps import list_steps
from semantics.registry.description import REGISTRY, REGISTRY_DUMP, REGISTRY_LICENSE, SPARQL_ENDPOINT
from semantics.registry.mappings import data_term, format_term
from semantics.namespaces import AMRF, BSC, COCOS, EDAM, SCHEMA, VOID
from semantics.registry.graph import build_registry_graph, step_resource
from semantics.registry.steps import port_iri


class RegistryGraphTests(SimpleTestCase):
    def setUp(self):
        self.graph = build_registry_graph(include_terms=False)

    def test_every_step_is_described(self):
        for step in list_steps():
            with self.subTest(step=step.key):
                self.assertIn((step_resource(step), RDF.type, SCHEMA.SoftwareApplication), self.graph)

    def test_graph_ports_match_the_ports_the_orchestrator_connects(self):
        """The orchestrator connects ports by (kind, format); the graph must say the same in EDAM."""
        for step in list_steps():
            resource = step_resource(step)
            for predicate, ports in ((BSC.input, step.consumes), (BSC.output, step.produces)):
                with self.subTest(step=step.key, predicate=predicate):
                    expected = {port_iri(resource, port.role) for port in ports}
                    self.assertEqual(set(self.graph.objects(resource, predicate)), expected)
                for port in ports:
                    node = port_iri(resource, port.role)
                    with self.subTest(step=step.key, port=port.role):
                        self.assertEqual(self.graph.value(node, SCHEMA.additionalType), data_term(port.kind))
                        self.assertEqual(self.graph.value(node, SCHEMA.encodingFormat), format_term(port.kind, port.format))


class RegistryDescriptionTests(SimpleTestCase):
    """The registry describes itself with VoID, counting what it has without that description."""

    def setUp(self):
        self.graph = build_registry_graph()
        self.content = len(self.graph) - len(list(self.graph.triples((REGISTRY, None, None))))

    def test_where_to_query_and_download_it_and_its_license(self):
        self.assertIn((REGISTRY, RDF.type, VOID.Dataset), self.graph)
        self.assertEqual(self.graph.value(REGISTRY, VOID.sparqlEndpoint), SPARQL_ENDPOINT)
        self.assertEqual(self.graph.value(REGISTRY, VOID.dataDump), REGISTRY_DUMP)  # not the dataset itself
        self.assertEqual(self.graph.value(REGISTRY, DCTERMS.license), REGISTRY_LICENSE)
        self.assertIn((REGISTRY, VOID.uriSpace, Literal(str(COCOS))), self.graph)  # a literal, as VoID asks
        self.assertIn((REGISTRY, VOID.exampleResource, COCOS['model/base_bakta_50']), self.graph)

    def test_its_numbers_and_vocabularies(self):
        self.assertEqual(self.graph.value(REGISTRY, VOID.triples).toPython(), self.content)
        self.assertGreater(self.graph.value(REGISTRY, VOID.entities).toPython(), 0)
        vocabularies = set(self.graph.objects(REGISTRY, VOID.vocabulary))
        self.assertTrue({URIRef(str(EDAM)), URIRef(str(SCHEMA)), URIRef(str(AMRF))} <= vocabularies)
        self.assertFalse({URIRef(str(COCOS)), URIRef(str(RDF))} & vocabularies)
