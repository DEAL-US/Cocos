from django.test import SimpleTestCase
from rdflib import URIRef

from semantics.flow import registry_flow, sample_flow
from semantics.namespaces import EDAM, OBO
from semantics.registry.graph import build_registry_graph
from semantics.tests.test_discovery import ANNOTATION, NANOPORE, READS, add_model, sample


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


class SampleFlowTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.registry = build_registry_graph()

    def nodes(self, flow):
        return {node['data']['id']: node['data'] for node in flow['nodes']}

    def test_the_data_it_has_and_the_preparation_the_models_need(self):
        nodes = self.nodes(sample_flow(self.registry, sample(('7', 'reads', READS, NANOPORE)), runs={}))

        reads = next(node for node in nodes.values() if node.get('detail') == 'FASTQ · Nanopore Sequencing')
        self.assertEqual(reads['files'], ['7'])
        self.assertEqual(nodes['step-assembly_ont_annotated']['state'], 'planned')
        self.assertEqual(nodes['step-assembly_ont_annotated']['for_models'], ['base_bakta_50', 'base_bakta_90'])
        self.assertEqual(nodes['step-extract_bakta_json']['state'], 'planned')
        self.assertEqual(nodes['step-assembly_ont']['state'], 'unused')  # the shortest path annotates in the same job
        self.assertEqual(nodes['model-base_bakta_50']['compatibility'], 'reachable')

    def test_the_latest_task_of_a_step_or_model(self):
        runs = {'step-assembly_ont_annotated': 'completed', 'step-extract_bakta_json': 'failed', 'model-base_bakta_50': 'pending'}
        nodes = self.nodes(sample_flow(self.registry, sample(('7', 'reads', READS, NANOPORE), ('8', 'annotation', ANNOTATION)), runs))

        self.assertEqual(nodes['step-assembly_ont_annotated']['state'], 'completed')
        self.assertEqual(nodes['step-extract_bakta_json']['state'], 'failed')
        self.assertEqual(nodes['model-base_bakta_50']['run'], 'pending')
        self.assertIsNone(nodes['model-base_bakta_90']['run'])

    def test_models_that_are_not_available_say_why(self):
        registry = build_registry_graph()
        add_model(registry, 'tb_model', READS, taxa=(OBO.NCBITaxon_1773,))

        nodes = self.nodes(sample_flow(registry, sample(('7', 'reads', READS, NANOPORE)), runs={}))

        self.assertEqual(nodes['model-tb_model']['compatibility'], 'incompatible')
        self.assertTrue(nodes['model-tb_model']['reasons'])
