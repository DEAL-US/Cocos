"""What the descriptors of models and parsers declare, read into plain Python for their registries.

The descriptors are the source of truth: the prediction registry takes the organisms,
antibiotics and ports of each model from here, and the gene extraction steps take the ports
and label of each parser. Labels of reused terms come from terms.ttl.
"""
from dataclasses import dataclass

from rdflib.namespace import RDFS

from core.steps import Port

from .descriptors import load_descriptor, model_descriptor_path, model_iri, parser_descriptor_path
from .mappings import file_type_of, kind_of
from .namespaces import AMRF, BSC, COCOS, OBO, SCHEMA
from .terms import terms_graph

# A model for Bacteria accepts a sample of any organism (v1: no other taxonomy reasoning).
ANY_BACTERIA = OBO.NCBITaxon_2


class DescriptorError(ValueError):
    pass


@dataclass(frozen=True)
class ModelDescription:
    inputs: tuple
    outputs: tuple
    any_organism: bool
    organisms: dict          # {'NCBITaxon:562': 'Escherichia coli'}
    antibiotics: tuple       # ARO labels, e.g. ('amikacin', 'meropenem')


@dataclass(frozen=True)
class ParserDescription:
    label: str
    inputs: tuple
    outputs: tuple


def describe_model(model_name):
    """Read the descriptor of a model. Raise DescriptorError if it is missing or incomplete."""
    graph = _load(model_descriptor_path(model_name))
    resource = model_iri(model_name)
    taxa = set(graph.objects(resource, SCHEMA.taxonomicRange))
    antibiotics = set(graph.objects(resource, AMRF.predictsResistanceTo))
    if not taxa or not antibiotics:
        raise DescriptorError(f'The descriptor of {model_name} must declare its organisms and antibiotics')
    return ModelDescription(
        inputs=_ports(graph, resource, BSC.input),
        outputs=_ports(graph, resource, BSC.output),
        any_organism=ANY_BACTERIA in taxa,
        organisms={_curie(taxon): _label(taxon) for taxon in taxa if taxon != ANY_BACTERIA},
        antibiotics=tuple(sorted(_label(antibiotic) for antibiotic in antibiotics)),
    )


def describe_parser(parser_name):
    """Read the descriptor of a parser, or return None if it has none (it is then not a step)."""
    path = parser_descriptor_path(parser_name)
    if not path.exists():
        return None
    graph = _load(path)
    resource = COCOS[f'step/extract_{parser_name}']
    return ParserDescription(
        label=str(graph.value(resource, SCHEMA.name)),
        inputs=_ports(graph, resource, BSC.input),
        outputs=_ports(graph, resource, BSC.output),
    )


def _load(path):
    if not path.exists():
        raise DescriptorError(f'Descriptor not found: {path}')
    return load_descriptor(path)


def _ports(graph, resource, predicate):
    ports = []
    for node in graph.objects(resource, predicate):
        role = graph.value(node, SCHEMA.name)
        data, file_format = graph.value(node, SCHEMA.additionalType), graph.value(node, SCHEMA.encodingFormat)
        try:
            ports.append(Port(str(role), kind_of(data), file_type_of(file_format)))
        except KeyError as error:
            raise DescriptorError(f'{node}: {error.args[0]}')
    return tuple(sorted(ports, key=lambda port: port.role))


def _label(term):
    label = terms_graph().value(term, RDFS.label)
    if label is None:
        raise DescriptorError(f'{term} has no label in terms.ttl: run `python manage.py fetch_terms`')
    return str(label)


def _curie(taxon):
    return 'NCBITaxon:' + str(taxon).rsplit('_', 1)[1]
