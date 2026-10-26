import copy
import tempfile
from pathlib import Path

from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, RDF

from conversion.tests.test_flows import ConversionFlowMixin, bakta_json
from core.models import TaskInput, TaskOutput, TaskStatus
from core.testing import FakeBioService
from prediction.models import PredictionRun, PredictionTask
from semantics.checks import check_trust_rules
from semantics.namespaces import COCOS, DQV, OA, OBO
from semantics.registry.graph import registry_graph
from semantics.sample import sample_graph
from semantics.trust import RULES, RulesError, antibiotic_iri, assess, check_rules, evidence, load_rules


class TrustRulesFileTests(SimpleTestCase):
    """trust_rules.toml holds every rule, and its mistakes are reported."""

    def setUp(self):
        self.config = load_rules()

    def broken(self, change):
        config = copy.deepcopy(self.config)
        change(config)
        with self.assertRaises(RulesError) as raised:
            check_rules(config)
        return str(raised.exception)

    def test_the_file_of_cocos_has_every_rule_and_level(self):
        self.assertEqual(set(self.config['rules']), set(RULES))
        self.assertEqual(self.config['levels']['serious'], 'Low')
        self.assertEqual(check_trust_rules(None), [])

    def test_mistakes_are_reported(self):
        cases = {
            'unknown rule': (lambda c: c['rules'].update(nonsense={}), 'nonsense'),
            'missing rule': (lambda c: c['rules'].pop('weights'), 'weights] is missing'),
            'threshold as text': (lambda c: c['rules']['antibiotic_isolates'].update(caution_below='500'),
                                  'caution_below must be a number'),
            'unknown judgement': (lambda c: c['rules']['species'].update(unknown='maybe'), 'unknown must be one of'),
            'missing text': (lambda c: c['rules']['model_quality']['text'].pop('caution'), 'has no "caution"'),
            'unknown value': (lambda c: c['rules']['model_quality']['text'].update(caution='{auc}'), 'unknown value'),
            'missing level': (lambda c: c['levels'].pop('caution'), '[levels] has no "caution"'),
        }
        for label, (change, message) in cases.items():
            with self.subTest(label):
                self.assertIn(message, self.broken(change))

    def test_a_file_that_cannot_be_read_is_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'rules.toml'
            path.write_text('[levels\n', encoding='utf-8')
            with self.assertRaisesMessage(RulesError, 'cannot be read'):
                load_rules(path)


SAMPLE = URIRef('https://cocos.example/processes/1')
MODEL = COCOS['model/base_bakta_50']
AMIKACIN = OBO.ARO_0000013


class TrustTests(ConversionFlowMixin, TestCase):
    """The trust of a prediction, from the provenance of its sample and the descriptor of its model."""

    def predict(self, organism='NCBITaxon:562'):
        """A prediction of amikacin by base_bakta_50 on the genes of the latest sample."""
        process = self.latest_process()
        process.organism = organism
        process.save(update_fields=['organism'])
        genes = TaskOutput.objects.get(task__process=process, role='genes').file
        run = PredictionRun.objects.create(process=process, selected_models=['base_bakta_50'],
                                           selected_antibiotics=['amikacin'])
        task = PredictionTask.objects.create(process=process, run=run, step='predict_base_bakta_50',
                                             status=TaskStatus.COMPLETED, parameters={'antibiotics': ['amikacin']},
                                             results={'amikacin': 0.2})
        TaskInput.objects.create(task=task, file=genes, role='genes')
        task.software = task.get_step().software(task)
        task.save(update_fields=['software'])
        return process, task

    def trust(self, process, task):
        graph = sample_graph(process, str(SAMPLE), with_provenance=True)
        facts = evidence(registry_graph(), graph, SAMPLE, URIRef(f'{SAMPLE}#task-{task.pk}'), MODEL, AMIKACIN)
        result = assess(registry_graph(), facts, 'amikacin')
        result['by_rule'] = {item['rule']: item for item in result['evidence']}
        return result

    def test_a_prediction_on_a_sample_annotated_by_cocos(self):
        with FakeBioService():
            self.run_assembly('ont', annotate=True)
        result = self.trust(*self.predict())
        by_rule = {rule: item['judgement'] for rule, item in result['by_rule'].items()}

        self.assertEqual(by_rule, {
            'species': 'for', 'antibiotic_isolates': 'for', 'class_balance': 'caution', 'species_isolates': 'for',
            'model_quality': 'for', 'same_annotation': 'caution', 'weights': 'for', 'annotation_origin': 'for',
        })
        self.assertEqual(result['level'], 'With reservations')
        self.assertEqual(result['evidence'][0]['judgement'], 'caution')  # worst first
        self.assertEqual(result['by_rule']['antibiotic_isolates']['text'],
                         'The model had 7,288 isolates with a known susceptibility to amikacin.')
        self.assertEqual(result['by_rule']['same_annotation']['text'],
                         'The input was annotated with Bakta 1.12.1 and Bakta database 6.0 (light), '
                         'and the data of the model with Bakta 1.9.4 and Bakta database (full).')
        self.assertIn('Escherichia coli', result['by_rule']['species_isolates']['text'])

    def test_an_uploaded_annotation_cannot_be_compared_with_the_training(self):
        with FakeBioService():
            self.client.post(reverse('conversion:annotation_from_json'), data={'feature_file': bakta_json()})
        result = self.trust(*self.predict())

        self.assertEqual(result['by_rule']['annotation_origin']['judgement'], 'caution')
        self.assertNotIn('same_annotation', result['by_rule'])

    def test_an_organism_the_model_was_not_built_for_is_low(self):
        with FakeBioService():
            self.run_assembly('ont', annotate=True)
        result = self.trust(*self.predict(organism='NCBITaxon:9606'))

        self.assertEqual(result['by_rule']['species']['judgement'], 'serious')
        self.assertEqual(result['by_rule']['species_isolates']['judgement'], 'caution')  # absent from its data
        self.assertEqual(result['level'], 'Low')

    def test_an_unknown_organism_skips_the_species_data(self):
        with FakeBioService():
            self.run_assembly('ont', annotate=True)
        result = self.trust(*self.predict(organism=''))

        self.assertEqual(result['by_rule']['species']['judgement'], 'caution')
        self.assertNotIn('species_isolates', result['by_rule'])

    def test_weights_that_are_not_the_declared_ones_are_serious(self):
        with FakeBioService():
            self.run_assembly('ont', annotate=True)
        process, task = self.predict()
        task.software[0]['weights'][0]['sha256'] = 'ab' * 32
        task.save(update_fields=['software'])

        self.assertEqual(self.trust(process, task)['by_rule']['weights']['judgement'], 'serious')

    def test_thresholds_and_switches_come_from_the_rules(self):
        with FakeBioService():
            self.run_assembly('ont', annotate=True)
        process, task = self.predict()
        graph = sample_graph(process, str(SAMPLE), with_provenance=True)
        facts = evidence(registry_graph(), graph, SAMPLE, URIRef(f'{SAMPLE}#task-{task.pk}'), MODEL, AMIKACIN)
        rules = load_rules()
        rules['rules']['antibiotic_isolates']['serious_below'] = 10_000
        rules['rules']['same_annotation']['enabled'] = False

        result = assess(registry_graph(), facts, 'amikacin', rules)
        judgements = {item['rule']: item['judgement'] for item in result['evidence']}
        self.assertEqual(judgements['antibiotic_isolates'], 'serious')
        self.assertNotIn('same_annotation', judgements)
        self.assertEqual(result['level'], 'Low')

    def test_the_antibiotic_of_a_model_by_its_name(self):
        self.assertEqual(antibiotic_iri(registry_graph(), MODEL, 'amikacin'), AMIKACIN)
        self.assertIsNone(antibiotic_iri(registry_graph(), MODEL, 'penicillin'))

    def test_the_rdf_of_the_sample_has_the_trust_of_each_prediction(self):
        with FakeBioService():
            self.run_assembly('ont', annotate=True)
        process, task = self.predict()
        response = self.client.get(reverse('semantics:process_rdf', args=[process.id]), {'format': 'ttl'})
        graph = Graph().parse(data=response.content, format='turtle')

        [annotation] = graph.subjects(RDF.type, DQV.QualityAnnotation)
        self.assertEqual(str(graph.value(annotation, OA.hasTarget)).rsplit('#', 1)[1], f'task-{task.pk}')
        self.assertEqual(graph.value(annotation, OA.motivatedBy), DQV.qualityAssessment)
        self.assertEqual(graph.value(annotation, OBO.IAO_0000136), AMIKACIN)
        self.assertEqual(graph.value(annotation, OA.bodyValue), Literal('With reservations', lang='en'))
        bodies = {str(graph.value(body, DCTERMS.identifier)): body for body in graph.objects(annotation, OA.hasBody)}
        self.assertEqual(len(bodies), 8)
        self.assertEqual(graph.value(bodies['class_balance'], DCTERMS.type), Literal('caution'))
        self.assertIn('8%', str(graph.value(bodies['class_balance'], RDF.value)))
