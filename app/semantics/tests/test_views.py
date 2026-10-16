from django.test import TestCase
from django.urls import reverse
from rdflib import Graph, URIRef

from conversion.tests.test_flows import ConversionFlowMixin, bakta_json
from core.testing import FakeBioService
from semantics.namespaces import SCHEMA


class ProcessRdfViewTests(ConversionFlowMixin, TestCase):
    def setUp(self):
        super().setUp()
        with FakeBioService():
            self.client.post(reverse('conversion:annotation_from_json'), data={'feature_file': bakta_json()})
        self.process = self.latest_process()
        self.url = reverse('semantics:process_rdf', args=[self.process.id])
        self.sample = URIRef(f'http://testserver{reverse("conversion:process_status", args=[self.process.id])}')

    def test_turtle_by_default_with_links_to_each_file(self):
        response = self.client.get(self.url)

        self.assertEqual(response['Content-Type'], 'text/turtle; charset=utf-8')
        graph = Graph().parse(data=response.content, format='turtle')
        parts = set(graph.objects(self.sample, SCHEMA.hasPart))
        self.assertEqual(len(parts), 2)
        for part in parts:
            with self.subTest(part=part):
                download = self.client.get(str(graph.value(part, SCHEMA.contentUrl)).removeprefix('http://testserver'))
                self.assertEqual(download.status_code, 200)

    def test_json_ld_when_asked_for(self):
        for kwargs in ({'data': {'format': 'jsonld'}}, {'HTTP_ACCEPT': 'application/ld+json'}):
            with self.subTest(**{key: str(value) for key, value in kwargs.items()}):
                response = self.client.get(self.url, **kwargs)
                self.assertEqual(response['Content-Type'], 'application/ld+json; charset=utf-8')
                graph = Graph().parse(data=response.content, format='json-ld')
                self.assertEqual(len(set(graph.objects(self.sample, SCHEMA.hasPart))), 2)

    def test_only_the_owner_gets_it(self):
        self.client.login(username='other-user', password='pass1234')
        self.assertEqual(self.client.get(self.url).status_code, 404)

        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
