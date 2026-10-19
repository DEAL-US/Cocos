from django.test import SimpleTestCase
from rdflib import Literal
from rdflib.namespace import RDFS

from semantics.registry.descriptors import load_descriptor, model_descriptor_path, model_iri
from semantics.namespaces import AMRF, OBO, SCHEMA
from semantics.registry.graph import build_registry_graph
from semantics.validation import validate, violations

MODEL = model_iri('base_bakta_50')
GENES = f'{MODEL}#genes'


def problems_of(graph):
    return {(problem.focus, problem.path, problem.severity) for problem in validate(graph)}


class RegistryValidationTests(SimpleTestCase):
    def test_the_registry_and_the_vocabulary_conform_to_the_shapes(self):
        """Fails when a descriptor, a generated step or the AMRF vocabulary breaks a shape."""
        self.assertEqual([str(problem) for problem in violations(validate(build_registry_graph(include_terms=False)))], [])

    def test_missing_recommended_properties_are_only_warnings(self):
        self.assertIn((str(MODEL), 'schema:license', 'Warning'), problems_of(load_descriptor(model_descriptor_path('base_bakta_50'))))


class ShapesCatchMistakesTests(SimpleTestCase):
    def setUp(self):
        self.graph = load_descriptor(model_descriptor_path('base_bakta_50'))

    def assertViolation(self, focus, path):
        self.assertIn((str(focus), path, 'Violation'), problems_of(self.graph))

    def test_a_tool_without_url(self):
        self.graph.remove((MODEL, SCHEMA.url, None))
        self.assertViolation(MODEL, 'schema:url')

    def test_an_antibiotic_that_is_not_an_antibiotic(self):
        self.graph.add((MODEL, AMRF.predictsResistanceTo, OBO.NCBITaxon_562))
        self.assertViolation(MODEL, 'amrf:predictsResistanceTo')

    def test_a_model_without_organisms(self):
        self.graph.remove((MODEL, SCHEMA.taxonomicRange, None))
        self.assertViolation(MODEL, 'schema:taxonomicRange')

    def test_a_parameter_without_format(self):
        self.graph.remove((None, SCHEMA.encodingFormat, None))
        self.assertViolation(GENES, 'schema:encodingFormat')

    def test_an_own_term_without_justification(self):
        self.graph.add((AMRF.newTerm, RDFS.label, Literal('new term')))
        self.graph.add((AMRF.newTerm, RDFS.comment, Literal('A term nobody justified.')))
        self.graph.add((AMRF.newTerm, RDFS.isDefinedBy, AMRF['']))
        self.assertViolation(AMRF.newTerm, 'skos:editorialNote')
