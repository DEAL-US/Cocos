from django.test import SimpleTestCase
from rdflib.namespace import RDF

from core.steps import list_steps
from semantics.registry.mappings import data_term, format_term
from semantics.namespaces import BSC, SCHEMA
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
