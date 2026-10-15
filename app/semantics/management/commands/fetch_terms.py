from django.core.management.base import BaseCommand, CommandError

from semantics.descriptors import all_descriptor_paths, load_descriptor
from semantics.registry import framework_steps
from semantics.steps_graph import steps_graph
from semantics.vocabulary import load_vocabulary
from semantics.terms import TERMS_FILE, TermError, fetch_terms, reused_terms, write_terms


class Command(BaseCommand):
    help = ('Look up in OLS every ontology term the registry uses and write their labels and '
            'hierarchy to terms.ttl. Run it after adding or changing a descriptor; needs internet.')

    def handle(self, *args, **options):
        # Read every descriptor file, not only the registered plug-ins: a model is not registered
        # until the terms it uses are in terms.ttl.
        graph = load_vocabulary() + steps_graph(framework_steps())
        for path in all_descriptor_paths():
            graph += load_descriptor(path)
        iris = reused_terms(graph)
        self.stdout.write(f'Looking up {len(iris)} terms in OLS...')
        try:
            graph = fetch_terms(iris)
        except TermError as error:
            raise CommandError(f'Some terms are not valid:\n{error}')
        write_terms(graph)
        self.stdout.write(self.style.SUCCESS(f'Wrote {len(graph)} triples to {TERMS_FILE}'))
