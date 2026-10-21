import json

from django.test import TestCase
from django.urls import reverse
from rdflib import Graph, Literal, URIRef
from rdflib.compare import isomorphic
from rdflib.namespace import RDF

from conversion.tests.test_flows import ConversionFlowMixin, bakta_json
from core.testing import FakeBioService
from semantics.namespaces import AMRF, COCOS, EDAM, SCHEMA

MODEL = COCOS['model/base_bakta_50']


class ResourcePagesTests(TestCase):
    """The IRIs of the registry resolve to a page for browsers and to RDF for RDF clients."""

    def test_a_model_is_a_page_for_browsers(self):
        response = self.client.get('/model/base_bakta_50', HTTP_ACCEPT='text/html')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, str(MODEL))
        self.assertContains(response, 'Gene report')                      # label of its input data
        self.assertContains(response, 'href="/model/base_bakta_50#genes"')  # its input, on the same page

    def test_a_model_is_turtle_or_json_ld_for_rdf_clients(self):
        turtle = Graph().parse(data=self.client.get('/model/base_bakta_50', HTTP_ACCEPT='text/turtle').content,
                               format='turtle')
        self.assertIn((MODEL, SCHEMA.featureList, EDAM.operation_3482), turtle)
        self.assertIn((URIRef(f'{MODEL}#genes'), SCHEMA.encodingFormat, EDAM.format_3464), turtle)

        json_ld = Graph().parse(data=self.client.get('/model/base_bakta_50?format=jsonld').content, format='json-ld')
        self.assertTrue(isomorphic(json_ld, turtle))  # the same graph (its blank nodes get new ids)

    def test_steps_vocabulary_and_shapes(self):
        step = Graph().parse(data=self.client.get('/step/bakta_annotation?format=ttl').content, format='turtle')
        self.assertIn((COCOS['step/bakta_annotation'], RDF.type, SCHEMA.SoftwareApplication), step)

        self.assertContains(self.client.get('/amrf/', HTTP_ACCEPT='text/html'), 'predicts resistance to')
        term = Graph().parse(data=self.client.get('/amrf/BaktaJSON?format=jsonld').content, format='json-ld')
        self.assertIn((AMRF.BaktaJSON, RDF.type, URIRef('http://www.w3.org/2002/07/owl#Class')), term)
        shapes = Graph().parse(data=self.client.get('/amrf/shapes?format=ttl').content, format='turtle')
        self.assertTrue(len(shapes))

    def test_the_registry_lists_every_model_and_step(self):
        response = self.client.get('/registry/', HTTP_ACCEPT='text/html')
        self.assertContains(response, 'href="/model/base_bakta_50"')
        self.assertContains(response, 'href="/step/bakta_annotation"')

    def test_the_registry_draws_its_data_flow(self):
        response = self.client.get('/registry/', HTTP_ACCEPT='text/html')
        self.assertContains(response, 'id="flow-data"')
        self.assertContains(response, '"url": "/model/base_bakta_50"')
        self.assertContains(response, 'vendor/cytoscape.min.js')

    def test_steps_and_models_link_to_their_node_in_the_data_flow(self):
        self.assertContains(self.client.get('/model/base_bakta_50', HTTP_ACCEPT='text/html'),
                            '/registry/?focus=model-base_bakta_50#data-flow')
        self.assertContains(self.client.get('/step/bakta_annotation', HTTP_ACCEPT='text/html'),
                            '/registry/?focus=step-bakta_annotation#data-flow')

    def test_unknown_resources_are_not_found(self):
        self.assertEqual(self.client.get('/model/no_such_model').status_code, 404)
        self.assertEqual(self.client.get('/amrf/noSuchTerm').status_code, 404)


class SparqlEndpointTests(ConversionFlowMixin, TestCase):
    """A public, read-only SPARQL endpoint over the registry only."""

    def query(self, query, method='get', accept=None, **kwargs):
        headers = {'HTTP_ACCEPT': accept} if accept else {}
        if method == 'get':
            return self.client.get(reverse('semantics:sparql'), {'query': query}, **headers)
        return self.client.post(reverse('semantics:sparql'), query, **headers, **kwargs)

    def test_select_with_the_usual_prefixes(self):
        self.client.logout()  # public
        response = self.query('SELECT ?model WHERE { ?model schema:featureList edam:operation_3482 }')

        self.assertEqual(response['Content-Type'], 'application/sparql-results+json; charset=utf-8')
        self.assertEqual(response['Access-Control-Allow-Origin'], '*')
        models = {row['model']['value'] for row in json.loads(response.content)['results']['bindings']}
        self.assertIn(str(MODEL), models)

    def test_result_formats(self):
        ask = self.query('ASK { ?s amrf:predictsResistanceTo ?o }')
        self.assertTrue(json.loads(ask.content)['boolean'])

        csv = self.query('SELECT ?s WHERE { ?s a schema:SoftwareApplication } LIMIT 1', accept='text/csv')
        self.assertEqual(csv['Content-Type'], 'text/csv; charset=utf-8')

        construct = self.query(f'CONSTRUCT {{ ?s ?p ?o }} WHERE {{ ?s ?p ?o FILTER(?s = <{MODEL}>) }}',
                               method='post', content_type='application/sparql-query')
        self.assertIn((MODEL, SCHEMA.taxonomicRange, None), Graph().parse(data=construct.content, format='turtle'))

    def test_refused_queries(self):
        cases = {
            'empty': '',
            'too long': 'SELECT * WHERE { ?s ?p ?o } #' + 'x' * 10_000,
            'update': 'INSERT DATA { <urn:a> <urn:b> <urn:c> }',
            'load': 'LOAD <http://example.org/data.ttl>',
            'service': 'SELECT * WHERE { SERVICE <http://example.org/sparql> { ?s ?p ?o } }',
        }
        for label, query in cases.items():
            with self.subTest(label):
                self.assertEqual(self.query(query).status_code, 400)

    def test_the_samples_of_the_users_are_never_exposed(self):
        with FakeBioService():
            self.client.post(reverse('conversion:annotation_from_json'), data={'feature_file': bakta_json()})

        response = self.query('ASK { ?sample a schema:Dataset }')

        self.assertFalse(json.loads(response.content)['boolean'])
        self.assertFalse(json.loads(self.query(f'ASK {{ ?s schema:name {Literal("sample.json").n3()} }}').content)['boolean'])
