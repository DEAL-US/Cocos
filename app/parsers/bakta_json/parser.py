"""Parser for the JSON feature files written by Bakta."""
import json

from django.db import transaction

from conversion.parsers import BaseParser, register_parser
from core.models import FileGene, Gene


@register_parser('bakta_json')
class BaktaJsonParser(BaseParser):
    default_options = {'complete_version': False}

    def read(self, file):
        try:
            with file.file.open('rb') as stored_file:
                return json.load(stored_file)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ValueError(f'Invalid JSON: {error}')

    def parse(self, data, file, user=None, options=None):
        """
        Parse a Bakta JSON feature file and create Gene, and FileGene entries.

        Reads `complete_version` from `options` (defaults to False).
        """
        complete_version = False if options is None else bool(options.get('complete_version', False))
        
        with transaction.atomic():
            features = data.get('features', [])
            try:
                for gene in features:
                    gene_name = gene.get('gene')
                    gene_db_xrefs = gene.get('db_xrefs')
                    gene_product = gene.get('product')
                    identifiers = []
                    if gene_db_xrefs:
                        for xref in gene_db_xrefs:
                            identifiers.append(xref)
                    if gene_product:
                        identifiers.append(gene_product)
                    if gene_name:
                        identifiers.append(gene_name)

                    identifiers = {ident.strip() for ident in identifiers if ident.strip()}
                    gene_obj = None
                    if identifiers:
                        # Get a gene with any of the identifiers, or create a new one
                        gene_obj = Gene.objects.search_identifiers(identifiers).first()
                        if not gene_obj:
                            gene_obj = Gene.objects.create()

                        gene_obj.add_identifiers(identifiers)

                    # Get expert type
                    expert_field = gene.get('expert')[0] if gene.get('expert') else None
                    expert_type = expert_field.get('type') if expert_field else 'unknown'

                    if gene_obj:
                        file_gene = FileGene.objects.create(
                            file=file,
                            gene=gene_obj,
                            expert=expert_type
                        )

                        if complete_version:
                            file_gene.start = gene.get('start')
                            file_gene.stop = gene.get('stop')
                            file_gene.nt = gene.get('nt')
                            file_gene.aa = gene.get('aa')
                            file_gene.save(update_fields=['start', 'stop', 'nt', 'aa'])

                        file.genes.add(gene_obj)

            except Exception as e:
                transaction.set_rollback(True)
                raise RuntimeError(f'Error parsing features: {str(e)}')

            return file
