from core.models import File, FileGene, Gene
from core.steps import DataKind
from django.db import transaction

# --- Registry for parsers ---
PARSERS = {}

def register_parser(name):
    """
    Decorator to register a parser instance under `name`.
    """
    def decorator(cls):
        PARSERS[name] = cls()
        return cls
    return decorator

def get_parser(name):
    return PARSERS.get(name)

# --- Main parsing function ---
def parse_file(parser, data, file, user=None, options=None):
    """
    Detect parser from `filename` extension and parse.
    Raises `RuntimeError` if no parser matches the extension.
    """
    parser = get_parser(parser)
    if not parser:
        raise RuntimeError(f'No parser registered for parser: {parser}')
    return parser.parse(data, file, user=user, options=options)

# --- Base Parser, extend this for specific file types or parsing ---
class BaseParser():
    # Parsers that declare what they consume become gene extraction steps (see conversion.steps).
    label = ''
    consumes_kind = None
    consumes_format = None
    default_options = {}

    def parse(self, data, file, user=None, options=None):
        """Parse data and persist results.

        `options` is a dict for parser-specific flags (e.g. {'complete_version': True}).
        If the parser is successful, it should return a `File` object.
        """
        raise NotImplementedError


# --- Example parser for Bakta JSON feature files ---
@register_parser('bakta_json')
class BaktaJsonParser(BaseParser):
    label = 'Bakta JSON'
    consumes_kind = DataKind.ANNOTATED_GENOME
    consumes_format = File.FileType.JSON
    default_options = {'complete_version': False}

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
