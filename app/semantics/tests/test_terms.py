from unittest import mock

from django.test import SimpleTestCase
from rdflib import Graph, URIRef
from rdflib.namespace import RDFS

from semantics.namespaces import OBO
from semantics.registry.descriptors import all_descriptor_paths, load_descriptor
from semantics.registry.graph import framework_steps
from semantics.registry.steps import steps_graph
from semantics.registry.vocabulary import load_vocabulary
from semantics.registry.terms import TERMS_FILE, TermError, _term_url, fetch_terms, reused_terms

MEROPENEM, CARBAPENEM = OBO.ARO_0000073, OBO.ARO_0000020


def fake_ols(terms):
    """A fake OLS `get`: `terms` maps IRIs to (label, parents, obsolete)."""
    def get(url, params=None, timeout=None):
        response = mock.Mock(status_code=404)
        for iri, (label, parents, obsolete) in terms.items():
            term_url = _term_url('aro', 'terms', iri)
            if url == term_url:
                response = mock.Mock(status_code=200)
                response.json.return_value = {'label': label, 'is_obsolete': obsolete}
            elif url == term_url + '/parents':
                response = mock.Mock(status_code=200)
                response.json.return_value = {'_embedded': {'terms': [{'iri': str(p)} for p in parents]}}
        return response
    return get


class FetchTermsTests(SimpleTestCase):
    def test_follows_the_parents_up_to_the_root(self):
        get = fake_ols({str(MEROPENEM): ('meropenem', [CARBAPENEM], False),
                        str(CARBAPENEM): ('carbapenem', [], False)})

        graph = fetch_terms({MEROPENEM}, get=get)

        self.assertIn((MEROPENEM, RDFS.subClassOf, CARBAPENEM), graph)
        self.assertEqual(str(graph.value(CARBAPENEM, RDFS.label)), 'carbapenem')

    def test_unknown_and_obsolete_terms_are_errors(self):
        get = fake_ols({str(MEROPENEM): ('meropenem', [], True)})

        with self.assertRaises(TermError) as raised:
            fetch_terms({MEROPENEM, OBO.ARO_9999999}, get=get)

        self.assertIn('ARO_0000073 (meropenem) is obsolete', str(raised.exception))
        self.assertIn('ARO_9999999 not found', str(raised.exception))


class TermsFileTests(SimpleTestCase):
    def test_every_reused_term_of_every_descriptor_has_a_label(self):
        """Fails when a descriptor uses a term not in terms.ttl: run `manage.py fetch_terms`.

        It reads every descriptor on disk, because a model whose terms are missing is not registered.
        """
        graph = load_vocabulary() + steps_graph(framework_steps())
        for path in all_descriptor_paths():
            graph += load_descriptor(path)
        terms = Graph().parse(TERMS_FILE, format='turtle')
        missing = [iri for iri in reused_terms(graph) if terms.value(URIRef(iri), RDFS.label) is None]
        self.assertEqual(missing, [])
