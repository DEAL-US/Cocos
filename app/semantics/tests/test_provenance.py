from django.conf import settings
from django.test import TestCase
from django.urls import reverse
from rdflib import Literal, URIRef
from rdflib.namespace import PROV, RDF, RDFS

from conversion.tests.test_flows import ConversionFlowMixin, bakta_json
from core.testing import FakeBioService
from semantics.namespaces import COCOS, SCHEMA
from semantics.sample import sample_graph

SAMPLE = URIRef('https://cocos.example/processes/1')


class ProvenanceTests(ConversionFlowMixin, TestCase):
    def provenance(self):
        process = self.latest_process()
        self.tasks = list(self.process_tasks(process))
        return sample_graph(process, str(SAMPLE), with_provenance=True)

    def activity(self, index):
        return URIRef(f'{SAMPLE}#task-{self.tasks[index].pk}')

    def entry(self, graph, role):
        return next(node for node in graph.objects(SAMPLE, SCHEMA.hasPart) if str(graph.value(node, SCHEMA.name)) == role)

    def test_each_task_is_an_activity_with_what_it_used_and_generated(self):
        with FakeBioService():
            self.run_assembly('ont', annotate=True)
        graph = self.provenance()
        assembly, extraction = self.activity(0), self.activity(1)

        for activity in (assembly, extraction):
            self.assertIn((activity, RDF.type, PROV.Activity), graph)
            self.assertEqual(graph.value(activity, SCHEMA.actionStatus), SCHEMA.CompletedActionStatus)
            self.assertIsNotNone(graph.value(activity, PROV.startedAtTime))
            self.assertIsNotNone(graph.value(activity, PROV.endedAtTime))
        self.assertIn((assembly, PROV.used, self.entry(graph, 'reads')), graph)
        self.assertIn((self.entry(graph, 'assembly'), PROV.wasGeneratedBy, assembly), graph)
        self.assertIn((self.entry(graph, 'annotation'), PROV.wasGeneratedBy, assembly), graph)
        self.assertIn((extraction, PROV.used, self.entry(graph, 'annotation')), graph)
        self.assertIn((self.entry(graph, 'genes'), PROV.wasGeneratedBy, extraction), graph)

    def test_activities_run_the_steps_of_the_registry_for_an_anonymous_user(self):
        with FakeBioService():
            self.run_assembly('ont', annotate=True)
        graph = self.provenance()
        user = URIRef(f'{SAMPLE}#user')

        self.assertIn((self.activity(0), PROV.wasAssociatedWith, COCOS['step/assembly_ont_annotated']), graph)
        self.assertIn((self.activity(1), PROV.wasAssociatedWith, COCOS['step/extract_bakta_json']), graph)
        self.assertIn((self.activity(0), PROV.wasAssociatedWith, user), graph)
        self.assertIn((user, RDF.type, PROV.Person), graph)
        self.assertIn((self.entry(graph, 'reads'), PROV.wasAttributedTo, user), graph)  # uploaded
        self.assertNotIn(self.user.username, graph.serialize(format='turtle'))

    def test_a_failed_task_is_an_activity_that_generated_nothing(self):
        with FakeBioService(status_sequence=['failed']):
            self.run_assembly('ont')
        graph = self.provenance()
        assembly = self.activity(0)

        self.assertEqual(graph.value(assembly, SCHEMA.actionStatus), SCHEMA.FailedActionStatus)
        self.assertIn((assembly, PROV.used, self.entry(graph, 'reads')), graph)
        self.assertEqual(list(graph.subjects(PROV.wasGeneratedBy, assembly)), [])

    def test_the_discovery_reads_the_sample_without_its_provenance(self):
        with FakeBioService():
            self.run_assembly('ont')

        graph = sample_graph(self.latest_process(), str(SAMPLE))
        self.assertEqual(list(graph.subjects(RDF.type, PROV.Activity)), [])

    def test_the_software_of_a_task_its_versions_and_identifiers(self):
        with FakeBioService():
            self.run_assembly('ont', annotate=True)
        graph = self.provenance()
        assembly = self.activity(0)
        agents = {str(graph.value(agent, RDFS.label)): agent for agent in graph.objects(assembly, PROV.wasAssociatedWith)
                  if (agent, RDF.type, PROV.SoftwareAgent) in graph}

        self.assertEqual(set(agents), {'Raven 1.8.3', 'Bakta 1.12.1', f'Cocos {settings.COCOS_VERSION}'})
        self.assertIn((agents['Raven 1.8.3'], PROV.specializationOf, URIRef('https://bio.tools/raven')), graph)
        self.assertEqual(graph.value(agents['Raven 1.8.3'], SCHEMA.softwareVersion), Literal('1.8.3'))
        database = URIRef('https://doi.org/10.5281/zenodo.14916843')
        self.assertIn((assembly, PROV.used, database), graph)
        self.assertIn((database, RDF.type, PROV.Entity), graph)
        self.assertEqual(graph.value(database, RDFS.label), Literal('Bakta database 6.0 (light)'))

    def test_a_prediction_used_its_model_and_the_weights_of_each_antibiotic(self):
        with FakeBioService():
            self.client.post(reverse('conversion:annotation_from_json'), data={'feature_file': bakta_json()})
        task = self.process_tasks(self.latest_process()).get()
        task.software = [{'name': 'base_bakta_50', 'version': '1.0.0', 'type': 'model',
                          'weights': [{'antibiotic': 'amikacin', 'sha256': 'ab' * 32}]}]
        task.save(update_fields=['software'])
        graph = self.provenance()

        model = next(graph.subjects(PROV.specializationOf, COCOS['model/base_bakta_50']))
        self.assertIn((self.activity(0), PROV.wasAssociatedWith, model), graph)
        weights = next(graph.subjects(SCHEMA.sha256, Literal('ab' * 32)))
        self.assertIn((self.activity(0), PROV.used, weights), graph)
