"""The assembler of ONT reads: Raven by default, or Flye if the user chooses it."""
from unittest.mock import Mock, patch

from django.test import TestCase
from django.urls import reverse

from conversion.tests.test_flows import ConversionFlowMixin, fastq
from core.models import ProcessGroup
from core.orchestration import permanent_failures
from core.steps import get_step
from core.testing import ASSEMBLY_SOFTWARE, FakeBioService


class OntAssemblerTests(ConversionFlowMixin, TestCase):

    def start_ont(self, assembler=None, annotate=False):
        data = {'assembly_type': 'ont', 'fastq_file': fastq('reads.fastq.gz', b'READS')}
        if assembler is not None:
            data['assembler'] = assembler
        if annotate:
            data['annotate'] = 'on'
        return self.client.post(reverse('conversion:assembly_run'), data=data)

    def assembly_task(self):
        return self.process_tasks(self.latest_process()).first()

    def test_raven_is_the_default(self):
        with FakeBioService() as bio:
            self.start_ont()

        [submission] = bio.submissions_to('assembly/ont')
        self.assertEqual(submission['assembler'], 'raven')
        task = self.assembly_task()
        self.assertEqual(task.parameters, {'assembler': 'raven'})
        self.assertIn('Raven', [entry['name'] for entry in task.software])

    def test_the_user_can_choose_flye(self):
        with FakeBioService() as bio:
            self.start_ont('flye', annotate=True)

        [submission] = bio.submissions_to('assembly/ont')
        self.assertEqual(submission['assembler'], 'flye')
        self.assertTrue(submission['annotate'])
        names = [entry['name'] for entry in self.assembly_task().software]
        self.assertIn('Flye', names)
        self.assertNotIn('Raven', names)

    def test_an_unknown_assembler_is_rejected(self):
        with FakeBioService() as bio:
            self.start_ont('spades')
            illumina = self.client.post(reverse('conversion:assembly_run'), data={
                'assembly_type': 'illumina', 'assembler': 'raven',
                'fastq_file': fastq('r1.fastq.gz'), 'fastq_file_2': fastq('r2.fastq.gz')})

        self.assertRedirects(illumina, reverse('conversion:assembly_ui'), fetch_redirect_response=False)
        self.assertFalse(ProcessGroup.objects.filter(user=self.user).exists())
        self.assertEqual(bio.submissions, [])

    def test_a_failure_for_good_with_flye_does_not_block_raven(self):
        with FakeBioService(status_sequence=['failed'], error_kind='input'):
            self.start_ont('flye')
            flye_failures = permanent_failures(self.latest_process())
        with FakeBioService(status_sequence=['failed'], error_kind='input'):
            self.start_ont('raven')
            raven_failures = permanent_failures(self.latest_process())

        self.assertNotIn('assembly_ont', {step for step, _ in flye_failures})
        self.assertIn('assembly_ont', {step for step, _ in raven_failures})


class OntAssemblerStepTests(TestCase):

    def test_a_plan_made_before_the_choice_uses_the_default_of_the_service(self):
        task = Mock(parameters={})
        task.read_input.return_value = b'READS'
        with patch('conversion.steps.bio_api_client.sequence_ont',
                   return_value={'status': 'pending', 'job_id': 'job-1'}) as sequence_ont:
            get_step('assembly_ont').process(task)

        sequence_ont.assert_called_once_with(b'READS', annotate=False, assembler=None)

    def test_a_service_that_does_not_list_its_assemblers_says_what_its_default_uses(self):
        tools = {'assembly': ASSEMBLY_SOFTWARE, 'annotation': []}
        self.assertEqual(get_step('assembly_ont').software_of(tools), ASSEMBLY_SOFTWARE['ont'])
