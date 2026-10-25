from django.test import TestCase
from django.urls import reverse
from rdflib import Literal, URIRef
from rdflib.namespace import RDF

from conversion.tests.test_flows import ConversionFlowMixin, bakta_json
from core.models import File, ProcessGroup
from core.testing import FakeBioService
from semantics.namespaces import AMRF, EDAM, OBO, SCHEMA
from semantics.sample import sample_graph
from semantics.validation import validate, violations

SAMPLE = 'https://cocos.example/processes/1'


class SampleGraphTests(ConversionFlowMixin, TestCase):
    def graph_of_latest_process(self):
        self.process = self.latest_process()
        return sample_graph(self.process, SAMPLE)

    def parts(self, graph):
        """{(role, data, format, technique)} of the data the sample has."""
        return {
            (str(graph.value(part, SCHEMA.name)), graph.value(part, SCHEMA.additionalType),
             graph.value(part, SCHEMA.encodingFormat), graph.value(part, SCHEMA.measurementTechnique))
            for part in graph.objects(URIRef(SAMPLE), SCHEMA.hasPart)
        }

    def test_an_uploaded_annotation_is_both_the_annotation_and_the_genes(self):
        with FakeBioService():
            self.client.post(reverse('conversion:annotation_from_json'),
                             data={'feature_file': bakta_json(), 'organism': ''})
        graph = self.graph_of_latest_process()

        sample = URIRef(SAMPLE)
        self.assertIn((sample, RDF.type, SCHEMA.Dataset), graph)
        self.assertEqual(graph.value(sample, SCHEMA.name), Literal(self.process.name))
        self.assertIsNone(graph.value(sample, SCHEMA.taxonomicRange))
        self.assertEqual(self.parts(graph), {
            ('annotation', EDAM.data_1270, AMRF.BaktaJSON, None),
            ('genes', EDAM.data_0916, None, None),  # kept in the database of Cocos, not a file
        })
        self.assertEqual(violations(validate(graph)), [])

    def test_an_annotated_ont_assembly_has_reads_assembly_annotation_and_genes(self):
        with FakeBioService():
            self.run_assembly('ont', annotate=True)
        graph = self.graph_of_latest_process()

        self.assertEqual(self.parts(graph), {
            ('reads', EDAM.data_3494, EDAM.format_1930, OBO.NCIT_C146818),
            ('assembly', EDAM.data_0925, EDAM.format_1929, None),
            ('annotation', EDAM.data_1270, AMRF.BaktaJSON, None),
            ('genes', EDAM.data_0916, None, None),
        })
        self.assertEqual(violations(validate(graph)), [])

    def test_the_reads_of_a_failed_assembly_are_still_part_of_the_sample(self):
        with FakeBioService(status_sequence=['failed']):
            self.run_assembly('illumina')
        graph = self.graph_of_latest_process()

        self.assertEqual(self.parts(graph), {
            ('r1', EDAM.data_3494, EDAM.format_1930, OBO.NCIT_C146817),
            ('r2', EDAM.data_3494, EDAM.format_1930, OBO.NCIT_C146817),
        })

    def test_files_have_their_sha256_and_the_genes_none(self):
        with FakeBioService():
            self.client.post(reverse('conversion:annotation_from_json'), data={'feature_file': bakta_json()})
        graph = self.graph_of_latest_process()

        checksums = {str(graph.value(part, SCHEMA.name)): graph.value(part, SCHEMA.sha256)
                     for part in graph.objects(URIRef(SAMPLE), SCHEMA.hasPart)}
        uploaded = File.objects.get(user=self.user)
        self.assertEqual(checksums, {'annotation': Literal(uploaded.sha256), 'genes': None})

    def test_the_organism_chosen_by_the_user(self):
        process = ProcessGroup.objects.create(name='isolate', user=self.user, organism='NCBITaxon:562')
        graph = sample_graph(process, SAMPLE)

        self.assertEqual(graph.value(URIRef(SAMPLE), SCHEMA.taxonomicRange), OBO.NCBITaxon_562)
