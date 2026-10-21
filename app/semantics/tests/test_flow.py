from django.test import SimpleTestCase
from rdflib import URIRef

from semantics.flow import registry_flow
from semantics.namespaces import EDAM
from semantics.registry.graph import build_registry_graph
from semantics.tests.test_discovery import add_model


class RegistryFlowTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.flow = registry_flow(build_registry_graph())

    def node(self, flow, **wanted):
        return next(node['data'] for node in flow['nodes']
                    if all(node['data'].get(key) == value for key, value in wanted.items()))

    def edges(self, flow):
        return {(edge['data']['source'], edge['data']['target']): edge['data']['roles'] for edge in flow['edges']}

    def test_steps_models_and_kinds_of_data_are_nodes(self):
        types = {node['data']['id']: node['data']['type'] for node in self.flow['nodes']}

        self.assertEqual(types['step-assembly_ont'], 'step')
        self.assertEqual(types['model-base_bakta_50'], 'model')
        assembly = self.node(self.flow, type='data', label='Sequence assembly')
        self.assertEqual(assembly['detail'], 'FASTA')
        self.assertEqual([term['iri'] for term in assembly['terms']], [str(EDAM.data_0925), str(EDAM.format_1929)])

    def test_reads_are_told_apart_by_their_sequencing_technique(self):
        nanopore = self.node(self.flow, type='data', detail='FASTQ · Nanopore Sequencing')['id']
        illumina = self.node(self.flow, type='data', detail='FASTQ · Illumina Sequencing')['id']
        edges = self.edges(self.flow)

        self.assertIn((nanopore, 'step-assembly_ont'), edges)
        self.assertNotIn((illumina, 'step-assembly_ont'), edges)
        self.assertEqual(edges[(illumina, 'step-assembly_illumina')], ['r1', 'r2'])  # one edge, two inputs

    def test_the_path_from_an_annotation_to_a_model(self):
        annotation = self.node(self.flow, type='data', label='Feature table')['id']
        genes = self.node(self.flow, type='data', label='Gene report')['id']
        edges = self.edges(self.flow)

        self.assertIn((annotation, 'step-extract_bakta_json'), edges)
        self.assertIn(('step-extract_bakta_json', genes), edges)
        self.assertIn((genes, 'model-base_bakta_50'), edges)

    def test_more_specific_data_feeds_a_more_general_input(self):
        registry = build_registry_graph()
        add_model(registry, 'json_model', (EDAM.data_1270, EDAM.format_3464))  # any JSON feature table

        flow = registry_flow(registry)
        bakta = self.node(flow, type='data', detail='Bakta JSON')['id']

        self.assertIn((bakta, 'model-json_model'), self.edges(flow))

    def test_tools_link_to_their_pages_and_models_say_what_they_predict(self):
        flow = registry_flow(build_registry_graph(), url_of=lambda iri: f'page:{iri}')
        model = self.node(flow, id='model-base_bakta_50')

        self.assertEqual(model['url'], 'page:' + str(URIRef('https://w3id.org/cocos/model/base_bakta_50')))
        self.assertIn('amikacin', model['antibiotics'])
        self.assertTrue(model['description'])
