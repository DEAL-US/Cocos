from django.test import SimpleTestCase
from rdflib import URIRef
from rdflib.namespace import RDF, RDFS, SKOS

from semantics.namespaces import AMRF
from semantics.vocabulary import load_vocabulary

ONTOLOGY = URIRef(str(AMRF))


class VocabularyTests(SimpleTestCase):
    def setUp(self):
        self.graph = load_vocabulary()

    def own_terms(self):
        subjects = {subject for subject in self.graph.subjects() if isinstance(subject, URIRef)}
        return sorted(term for term in subjects if str(term).startswith(str(AMRF)) and term != ONTOLOGY)

    def test_every_own_term_is_documented_and_justified(self):
        terms = self.own_terms()
        self.assertTrue(terms)
        for term in terms:
            for predicate in (RDF.type, RDFS.label, RDFS.comment, SKOS.editorialNote):
                with self.subTest(term=term, predicate=predicate):
                    self.assertIsNotNone(self.graph.value(term, predicate))
            with self.subTest(term=term):
                self.assertEqual(self.graph.value(term, RDFS.isDefinedBy), ONTOLOGY)

