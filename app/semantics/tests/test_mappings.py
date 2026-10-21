from django.test import SimpleTestCase

from core.models import File
from core.steps import DataKind, get_step, list_steps
from semantics.registry.mappings import (DATA, FORMATS, data_term, file_type_of, format_term, operation_terms,
                                         sequencing_technique)
from semantics.namespaces import AMRF, EDAM, OBO


class MappingTests(SimpleTestCase):
    def test_every_data_kind_and_file_type_has_a_term(self):
        self.assertEqual(set(DATA), set(DataKind))
        self.assertEqual(set(FORMATS), set(File.FileType))

    def test_every_registered_step_can_be_described(self):
        for step in list_steps():
            with self.subTest(step=step.key):
                self.assertTrue(operation_terms(step))
                sequencing_technique(step)
                for port in step.consumes + step.produces:
                    data_term(port.kind)
                    format_term(port.kind, port.format)

    def test_annotations_are_bakta_json_and_other_json_is_generic(self):
        self.assertEqual(format_term(DataKind.ANNOTATED_GENOME, File.FileType.JSON), AMRF.BaktaJSON)
        self.assertEqual(format_term(DataKind.ANNOTATED_GENOME, File.FileType.CSV), EDAM.format_3752)

    def test_the_genes_have_no_format_and_are_linked_to_a_json_file(self):
        self.assertIsNone(format_term(DataKind.GENE_SET, File.FileType.JSON))
        self.assertEqual(file_type_of(None, DataKind.GENE_SET), File.FileType.JSON)

    def test_an_assembly_that_annotates_performs_both_operations(self):
        self.assertEqual(operation_terms(get_step('assembly_ont_annotated')),
                         [EDAM.operation_0525, EDAM.operation_0362])
        self.assertEqual(sequencing_technique(get_step('assembly_illumina')), OBO.NCIT_C146817)
        self.assertIsNone(sequencing_technique(get_step('bakta_annotation')))
