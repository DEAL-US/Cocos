from django.conf import settings
from django.test import TestCase
from django.urls import reverse
from rdflib import Literal, URIRef
from rdflib.namespace import DCTERMS, PROV, RDF, RDFS

from conversion.tests.test_flows import ConversionFlowMixin, bakta_json
from core.testing import FakeBioService
from semantics.namespaces import COCOS, PPLAN, SCHEMA
from semantics.sample import sample_graph
from semantics.validation import validate, violations

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
        self.assertEqual(graph.value(assembly, SCHEMA.error), Literal('Annotation failed: Command failed: bakta'))
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
                          'weights': [{'antibiotic': 'amikacin', 'sha256': 'ab' * 32}, {'sha256': 'cd' * 32}]}]
        task.save(update_fields=['software'])
        graph = self.provenance()

        model = next(graph.subjects(PROV.specializationOf, COCOS['model/base_bakta_50']))
        self.assertIn((self.activity(0), PROV.wasAssociatedWith, model), graph)
        weights = next(graph.subjects(SCHEMA.sha256, Literal('ab' * 32)))
        self.assertIn((self.activity(0), PROV.used, weights), graph)
        self.assertEqual(graph.value(weights, RDFS.label), Literal('base_bakta_50 weights for amikacin'))
        shared = next(graph.subjects(SCHEMA.sha256, Literal('cd' * 32)))  # for all the antibiotics
        self.assertIn((self.activity(0), PROV.used, shared), graph)
        self.assertEqual(graph.value(shared, RDFS.label), Literal('base_bakta_50 weights'))

    def test_the_plan_its_order_and_the_activity_that_carried_out_each_step(self):
        with FakeBioService():
            self.run_assembly('ont', annotate=True)
        graph = self.provenance()
        plan = URIRef(f'{SAMPLE}#plan')
        assembly_step, extraction_step = (URIRef(f'{SAMPLE}#plan-{task.plan_node}') for task in self.tasks)

        self.assertIn((plan, RDF.type, PPLAN.Plan), graph)
        self.assertIn((extraction_step, PPLAN.isStepOfPlan, plan), graph)
        self.assertIn((extraction_step, PPLAN.isPrecededBy, assembly_step), graph)
        self.assertIn((assembly_step, DCTERMS.type, COCOS['step/assembly_ont_annotated']), graph)
        self.assertIn((self.activity(0), PPLAN.correspondsToStep, assembly_step), graph)
        self.assertIn((self.activity(1), PPLAN.correspondsToStep, extraction_step), graph)

    def test_a_cancelled_step_of_the_plan_has_no_activity(self):
        with FakeBioService():
            self.run_assembly('ont')
        process = self.latest_process()
        process.plan.append({'id': 'n9', 'step': 'bakta_annotation', 'after': ['n1'], 'batch': 2,
                             'parameters': {}, 'cancelled': True})
        process.save(update_fields=['plan'])
        graph = self.provenance()
        cancelled = URIRef(f'{SAMPLE}#plan-n9')

        self.assertIn((cancelled, RDF.type, PPLAN.Step), graph)
        self.assertIsNotNone(graph.value(cancelled, RDFS.comment))
        self.assertEqual(list(graph.subjects(PPLAN.correspondsToStep, cancelled)), [])


class ProvenanceShapesTests(ConversionFlowMixin, TestCase):
    def setUp(self):
        super().setUp()
        with FakeBioService():
            self.run_assembly('ont', annotate=True)
        process = self.latest_process()
        self.graph = sample_graph(process, str(SAMPLE), with_provenance=True)
        self.assembly = URIRef(f'{SAMPLE}#task-{self.process_tasks(process).first().pk}')

    def assertViolation(self, focus, path):
        self.assertIn((str(focus), path), {(problem.focus, problem.path) for problem in violations(validate(self.graph))})

    def test_the_provenance_of_a_sample_conforms_to_the_shapes(self):
        self.assertEqual([str(problem) for problem in violations(validate(self.graph))], [])

    def test_a_finished_activity_without_its_end(self):
        self.graph.remove((self.assembly, PROV.endedAtTime, None))
        self.assertViolation(self.assembly, '')  # the sh:or of the activity shape

    def test_software_without_version(self):
        raven = next(self.graph.subjects(SCHEMA.name, Literal('Raven')))
        self.graph.remove((raven, SCHEMA.softwareVersion, None))
        self.assertViolation(raven, 'schema:softwareVersion')

    def test_a_malformed_checksum(self):
        reads = next(part for part in self.graph.objects(SAMPLE, SCHEMA.hasPart) if self.graph.value(part, SCHEMA.sha256))
        self.graph.set((reads, SCHEMA.sha256, Literal('not a sha256')))
        self.assertViolation(reads, 'schema:sha256')
