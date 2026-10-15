from django.test import SimpleTestCase
from rdflib import URIRef
from rdflib.namespace import DCTERMS, OWL, RDF, RDFS, SKOS

from semantics.namespaces import AMRF, OBO, VANN
from semantics.vocabulary import load_vocabulary

ONTOLOGY = URIRef(str(AMRF))


class VocabularyTests(SimpleTestCase):
    def setUp(self):
        self.graph = load_vocabulary()

    def own_terms(self):
        subjects = {subject for subject in self.graph.subjects() if isinstance(subject, URIRef)}
        return sorted(term for term in subjects if str(term).startswith(str(AMRF)) and term != ONTOLOGY)

    def test_header_declares_what_reusers_need(self):
        self.assertIn((ONTOLOGY, RDF.type, OWL.Ontology), self.graph)
        for predicate in (DCTERMS.title, DCTERMS.license, OWL.versionInfo, OWL.versionIRI,
                          VANN.preferredNamespacePrefix, VANN.preferredNamespaceUri):
            with self.subTest(predicate=predicate):
                self.assertIsNotNone(self.graph.value(ONTOLOGY, predicate))

    def test_every_own_term_is_documented_and_justified(self):
        terms = self.own_terms()
        self.assertTrue(terms)
        for term in terms:
            for predicate in (RDF.type, RDFS.label, RDFS.comment, SKOS.editorialNote):
                with self.subTest(term=term, predicate=predicate):
                    self.assertIsNotNone(self.graph.value(term, predicate))
            with self.subTest(term=term):
                self.assertEqual(self.graph.value(term, RDFS.isDefinedBy), ONTOLOGY)

    def test_predicts_resistance_to_specializes_is_about_and_ranges_over_antibiotics(self):
        self.assertIn((AMRF.predictsResistanceTo, RDFS.subPropertyOf, OBO.IAO_0000136), self.graph)
        self.assertIn((AMRF.predictsResistanceTo, RDFS.range, OBO.ARO_1000003), self.graph)
