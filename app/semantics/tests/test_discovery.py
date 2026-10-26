from django.test import SimpleTestCase
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, RDFS

from semantics.discovery import Source, Status, discover
from semantics.namespaces import AMRF, BIOSCHEMAS, BSC, EDAM, OBO, SCHEMA
from semantics.registry.graph import build_registry_graph

SAMPLE = URIRef('https://cocos.example/processes/1')
ILLUMINA, NANOPORE = OBO.NCIT_C146817, OBO.NCIT_C146818

READS = (EDAM.data_3494, EDAM.format_1930)
ASSEMBLY = (EDAM.data_0925, EDAM.format_1929)
ANNOTATION = (EDAM.data_1270, AMRF.BaktaJSON)
GENES = (EDAM.data_0916, None)  # kept in the database of Cocos: no file format


def sample(*entries, taxon=None):
    """A sample graph; each entry is (file id, role, (data, format)[, technique])."""
    graph = Graph()
    graph.add((SAMPLE, RDF.type, SCHEMA.Dataset))
    if taxon is not None:
        graph.add((SAMPLE, SCHEMA.taxonomicRange, taxon))
    for file_id, role, (data, file_format), *technique in entries:
        node = URIRef(f'{SAMPLE}#file-{file_id}-{role}')
        graph.add((SAMPLE, SCHEMA.hasPart, node))
        graph.add((node, SCHEMA.identifier, Literal(file_id)))
        graph.add((node, SCHEMA.name, Literal(role)))
        graph.add((node, SCHEMA.additionalType, data))
        if file_format is not None:
            graph.add((node, SCHEMA.encodingFormat, file_format))
        if technique:
            graph.add((node, SCHEMA.measurementTechnique, technique[0]))
    return graph


def add_model(graph, identifier, consumes, taxa=(OBO.NCBITaxon_2,), antibiotics=(OBO.ARO_0000013,)):
    """Add to `graph` a model that consumes (data, format), for `taxa` and `antibiotics`."""
    model = URIRef(f'https://w3id.org/cocos/model/{identifier}')
    parameter = URIRef(f'{model}#input')
    graph.add((model, RDF.type, SCHEMA.SoftwareApplication))
    graph.add((model, SCHEMA.identifier, Literal(identifier)))
    graph.add((model, SCHEMA.featureList, EDAM.operation_3482))
    graph.add((model, BSC.input, parameter))
    graph.add((parameter, RDF.type, BIOSCHEMAS.FormalParameter))
    graph.add((parameter, SCHEMA.name, Literal('input')))
    graph.add((parameter, SCHEMA.additionalType, consumes[0]))
    if consumes[1] is not None:
        graph.add((parameter, SCHEMA.encodingFormat, consumes[1]))
    for taxon in taxa:
        graph.add((model, SCHEMA.taxonomicRange, taxon))
    for antibiotic in antibiotics:
        graph.add((model, AMRF.predictsResistanceTo, antibiotic))


class DiscoveryTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.registry = build_registry_graph()

    def compatibility(self, sample_graph, model='base_bakta_50', registry=None, **kwargs):
        results = discover(registry if registry is not None else self.registry, sample_graph, **kwargs)
        return next(result for result in results if result.model == model)

    def steps(self, result):
        return [step.step for step in result.steps]

    def test_a_sample_with_genes_is_ready(self):
        result = self.compatibility(sample(('12', 'annotation', ANNOTATION), ('12', 'genes', GENES)))

        self.assertEqual(result.status, Status.READY)
        self.assertEqual(result.inputs, (('genes', Source('genes', file='12')),))

    def test_an_annotation_needs_the_gene_extraction(self):
        result = self.compatibility(sample(('12', 'annotation', ANNOTATION)))

        self.assertEqual((result.status, self.steps(result)), (Status.REACHABLE, ['extract_bakta_json']))
        self.assertEqual(result.steps[0].inputs, (('annotation', Source('annotation', file='12')),))
        self.assertEqual(result.inputs, (('genes', Source('genes', step=0)),))

    def test_ont_reads_are_assembled_and_annotated_in_one_job(self):
        result = self.compatibility(sample(('7', 'reads', READS, NANOPORE)))

        self.assertEqual(self.steps(result), ['assembly_ont_annotated', 'extract_bakta_json'])
        self.assertEqual(result.steps[0].inputs, (('reads', Source('reads', file='7')),))
        self.assertEqual(result.steps[1].inputs, (('annotation', Source('annotation', step=0)),))

    def test_an_existing_assembly_is_annotated_not_assembled_again(self):
        result = self.compatibility(sample(('7', 'reads', READS, NANOPORE), ('9', 'assembly', ASSEMBLY)))

        self.assertEqual(self.steps(result), ['bakta_annotation', 'extract_bakta_json'])
        self.assertEqual(result.steps[0].inputs, (('assembly', Source('assembly', file='9')),))

    def test_illumina_reads_need_both_files(self):
        pair = sample(('7', 'r1', READS, ILLUMINA), ('8', 'r2', READS, ILLUMINA))
        result = self.compatibility(pair)

        self.assertEqual(self.steps(result), ['assembly_illumina_annotated', 'extract_bakta_json'])
        self.assertEqual(result.steps[0].inputs, (('r1', Source('r1', file='7')), ('r2', Source('r2', file='8'))))

        result = self.compatibility(sample(('7', 'r1', READS, ILLUMINA)))
        self.assertEqual(result.status, Status.INCOMPATIBLE)
        self.assertIn('no steps can obtain it', result.reasons[0])

    def test_a_model_that_consumes_an_assembly_does_not_go_through_genes(self):
        registry = build_registry_graph()
        add_model(registry, 'fasta_model', ASSEMBLY)

        result = self.compatibility(sample(('7', 'reads', READS, NANOPORE)), 'fasta_model', registry)

        self.assertEqual(self.steps(result), ['assembly_ont'])

    def test_a_json_file_of_genes_is_not_the_genes_cocos_extracted(self):
        result = self.compatibility(sample(('9', 'genes', (EDAM.data_0916, EDAM.format_3464))))

        self.assertEqual(result.status, Status.INCOMPATIBLE)

    def test_a_bakta_annotation_is_json_but_json_is_not_a_bakta_annotation(self):
        registry = build_registry_graph()
        add_model(registry, 'json_model', (EDAM.data_1270, EDAM.format_3464))
        add_model(registry, 'bakta_model', ANNOTATION)
        generic = sample(('12', 'annotation', (EDAM.data_1270, EDAM.format_3464)))

        self.assertEqual(self.compatibility(sample(('12', 'annotation', ANNOTATION)), 'json_model', registry).status,
                         Status.READY)
        self.assertEqual(self.compatibility(generic, 'bakta_model', registry).status, Status.INCOMPATIBLE)

    def test_organisms(self):
        registry = build_registry_graph()
        registry.add((OBO.NCBITaxon_1773, RDFS.label, Literal('Mycobacterium tuberculosis')))
        add_model(registry, 'tb_model', GENES, taxa=(OBO.NCBITaxon_1773,))
        genes = ('12', 'genes', GENES)

        cases = [
            (OBO.NCBITaxon_1773, Status.READY, None),
            (OBO.NCBITaxon_562, Status.INCOMPATIBLE, 'only for Mycobacterium tuberculosis, and this sample is'),
            (None, Status.INCOMPATIBLE, 'organism of this sample is unknown'),
        ]
        for taxon, status, reason in cases:
            with self.subTest(taxon=taxon):
                result = self.compatibility(sample(genes, taxon=taxon), 'tb_model', registry)
                self.assertEqual(result.status, status)
                if reason:
                    self.assertIn(reason, result.reasons[0])
        # base_bakta_50 is for Bacteria: any organism, also an unknown one.
        self.assertEqual(self.compatibility(sample(genes)).status, Status.READY)

    def test_a_model_for_a_taxon_accepts_the_taxa_under_it(self):
        registry = build_registry_graph()
        add_model(registry, 'enterobacterales_model', GENES, taxa=(OBO.NCBITaxon_91347,))  # Enterobacterales
        genes = ('12', 'genes', GENES)

        for taxon, status in ((OBO.NCBITaxon_562, Status.READY),          # Escherichia coli
                              (OBO.NCBITaxon_28901, Status.READY),        # Salmonella enterica
                              (OBO.NCBITaxon_470, Status.INCOMPATIBLE)):  # Acinetobacter baumannii
            with self.subTest(taxon=taxon):
                result = self.compatibility(sample(genes, taxon=taxon), 'enterobacterales_model', registry)
                self.assertEqual(result.status, status)

    def test_antibiotics_are_optional(self):
        genes = sample(('12', 'genes', GENES))

        self.assertEqual(self.compatibility(genes, antibiotics=['meropenem']).status, Status.READY)
        result = self.compatibility(genes, antibiotics=['vancomycin'])
        self.assertEqual(result.status, Status.INCOMPATIBLE)
        self.assertIn('none of the selected antibiotics', result.reasons[0])
