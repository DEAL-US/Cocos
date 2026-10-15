from django.core.management.base import BaseCommand, CommandError

from semantics.registry import build_registry_graph
from semantics.terms import TERMS_FILE, TermError, fetch_terms, reused_terms, write_terms


class Command(BaseCommand):
    help = ('Look up in OLS every ontology term the registry uses and write their labels and '
            'hierarchy to terms.ttl. Run it after adding or changing a descriptor; needs internet.')

    def handle(self, *args, **options):
        iris = reused_terms(build_registry_graph(include_terms=False))
        self.stdout.write(f'Looking up {len(iris)} terms in OLS...')
        try:
            graph = fetch_terms(iris)
        except TermError as error:
            raise CommandError(f'Some terms are not valid:\n{error}')
        write_terms(graph)
        self.stdout.write(self.style.SUCCESS(f'Wrote {len(graph)} triples to {TERMS_FILE}'))
