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
        self.assertEqual(len(parts), 2)  # the annotation and the genes
        downloads = [graph.value(part, SCHEMA.contentUrl) for part in parts]
        self.assertEqual(downloads.count(None), 1)  # the genes are in the database, not a file
        for url in filter(None, downloads):
            self.assertEqual(self.client.get(str(url).removeprefix('http://testserver')).status_code, 200)

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


class ProcessFlowViewTests(ConversionFlowMixin, TestCase):
    def setUp(self):
        super().setUp()
        with FakeBioService():
            self.client.post(reverse('conversion:annotation_from_json'), data={'feature_file': bakta_json()})
        self.process = self.latest_process()
        self.url = reverse('semantics:process_flow', args=[self.process.id])

    def test_the_flow_with_the_state_of_the_sample_and_links_to_its_files(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        nodes = {node['data']['id']: node['data'] for node in response.context['flow']['nodes']}
        self.assertEqual(nodes['step-extract_bakta_json']['state'], 'completed')
        self.assertEqual(nodes['model-base_bakta_50']['compatibility'], 'ready')
        files = response.context['files']
        annotation = next(node for node in nodes.values() if node.get('label') == 'Feature table')
        self.assertEqual(self.client.get(files[annotation['files'][0]]['url']).status_code, 200)
        self.assertContains(response, 'id="flow-files"')

    def test_the_page_of_the_process_links_to_it(self):
        self.assertContains(self.client.get(reverse('conversion:process_status', args=[self.process.id])), self.url)

    def test_only_the_owner_gets_it(self):
        self.client.login(username='other-user', password='pass1234')
        self.assertEqual(self.client.get(self.url).status_code, 404)

        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
