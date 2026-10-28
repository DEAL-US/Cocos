from django.test import SimpleTestCase
from rdflib import Literal
from rdflib.namespace import RDF

from core.steps import get_step
from semantics.namespaces import AMRF, BIOSCHEMAS, BSC, COCOS, EDAM, OBO, SCHEMA
from semantics.registry.steps import steps_graph


class StepsGraphTests(SimpleTestCase):
    def test_describes_a_step_as_a_tool_with_its_inputs_and_outputs(self):
        graph = steps_graph([get_step('assembly_illumina')])
        step = COCOS['step/assembly_illumina']
        r1 = COCOS['step/assembly_illumina#r1']

        self.assertIn((step, RDF.type, SCHEMA.SoftwareApplication), graph)
        self.assertIn((step, SCHEMA.featureList, EDAM.operation_0525), graph)
        self.assertEqual(graph.value(step, SCHEMA.applicationCategory), Literal('Web service'))
        self.assertTrue(str(graph.value(step, SCHEMA.description)))
        self.assertEqual(str(graph.value(step, SCHEMA.url)),
                         'https://github.com/DEAL-US/Cocos/blob/main/app/conversion/steps.py')
        self.assertEqual(set(graph.objects(step, BSC.input)), {r1, COCOS['step/assembly_illumina#r2']})
        self.assertIn((r1, RDF.type, BIOSCHEMAS.FormalParameter), graph)
        self.assertIn((r1, SCHEMA.name, Literal('r1')), graph)
        self.assertIn((r1, SCHEMA.additionalType, EDAM.data_3494), graph)
        self.assertIn((r1, SCHEMA.encodingFormat, EDAM.format_1930), graph)
        self.assertIn((r1, SCHEMA.measurementTechnique, OBO.NCIT_C146817), graph)

        assembly = COCOS['step/assembly_illumina#assembly']
        self.assertEqual(set(graph.objects(step, BSC.output)), {assembly})
        self.assertIsNone(graph.value(assembly, SCHEMA.measurementTechnique))

    def test_annotation_outputs_are_bakta_json(self):
        graph = steps_graph([get_step('bakta_annotation')])

        self.assertIn((COCOS['step/bakta_annotation#annotation'], SCHEMA.encodingFormat, AMRF.BaktaJSON), graph)
