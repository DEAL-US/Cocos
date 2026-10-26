import pkgutil

from django.test import SimpleTestCase
from rdflib import Literal, URIRef
from rdflib.namespace import PROV, RDF

import parsers
from prediction.adapters.registry import list_registered_models
from semantics.registry.graph import build_registry_graph
from semantics.registry.descriptors import load_descriptor, model_descriptor_path, model_iri, parser_descriptor_path
from semantics.namespaces import COCOS, SCHEMA


class DescriptorTests(SimpleTestCase):
    def test_every_model_has_a_descriptor_of_itself(self):
        for name in list_registered_models():
            with self.subTest(model=name):
                graph = load_descriptor(model_descriptor_path(name))
                self.assertIn((model_iri(name), RDF.type, SCHEMA.SoftwareApplication), graph)
                self.assertEqual(graph.value(model_iri(name), SCHEMA.identifier), Literal(name))

    def test_every_parser_folder_has_a_descriptor_of_its_extraction_step(self):
        for name in (module.name for module in pkgutil.iter_modules(parsers.__path__) if module.ispkg):
            with self.subTest(parser=name):
                step = COCOS[f'step/extract_{name}']
                graph = load_descriptor(parser_descriptor_path(name))
                self.assertIn((step, RDF.type, SCHEMA.SoftwareApplication), graph)
                self.assertEqual(graph.value(step, SCHEMA.identifier), Literal(f'extract_{name}'))


class ModelProvenanceTests(SimpleTestCase):
    """The descriptors say how each model was built, with the PROV-O pattern of the provenance of a
    sample, so that one query answers both."""

    QUERY = '''
        SELECT ?version WHERE {
            ?model prov:wasDerivedFrom/prov:wasGeneratedBy/prov:wasAssociatedWith ?agent .
            ?agent prov:specializationOf <https://bio.tools/bakta> ; schema:softwareVersion ?version .
        }'''

    def test_the_genomes_of_the_training_data_were_annotated_with_bakta_1_9_4(self):
        registry = build_registry_graph()
        for name in ('base_bakta_50', 'base_bakta_90'):
            with self.subTest(model=name):
                rows = registry.query(self.QUERY, initNs={'prov': PROV, 'schema': SCHEMA},
                                      initBindings={'model': model_iri(name)})
                self.assertEqual([str(row.version) for row in rows], ['1.9.4'])

    def test_the_training_data_is_part_of_the_published_dataset(self):
        registry = build_registry_graph()
        data = registry.value(model_iri('base_bakta_50'), PROV.wasDerivedFrom)
        self.assertEqual(registry.value(data, SCHEMA.isPartOf), URIRef('https://doi.org/10.6019/S-BSST2698'))
