"""The registry as a data flow: which kinds of data each step and model consumes and produces.

It is drawn on the registry page. The nodes are the kinds of data (EDAM data + format, and the
sequencing technique of reads), the steps and the models. A kind of data points to every step or
model it can feed and a step points to the data it produces, decided with the same reading
(read_tools) and matching (satisfies) as the discovery, so the drawing shows the paths the
discovery can take.

The result is plain data in the elements format of Cytoscape.js.
"""
from .discovery.graphs import label, read_tools
from .discovery.search import satisfies


def registry_flow(registry, url_of=str):
    """{'nodes': [...], 'edges': [...]} of `registry` (a graph). `url_of(iri)` gives the page of a
    step, model or ontology term."""
    tools = read_tools(registry)
    kinds = sorted({parameter.kind for tool in tools for parameter in tool.inputs + tool.outputs},
                   key=lambda kind: _kind_label(registry, kind))
    kind_ids = {kind: f'data-{index}' for index, kind in enumerate(kinds)}

    nodes = [_data_node(registry, kind, kind_ids[kind], url_of) for kind in kinds]
    nodes += [_tool_node(tool, url_of) for tool in tools]

    edges = []
    for tool in tools:
        tool_id = tool_node_id(tool.identifier, tool.is_model)
        roles = {}  # source kind -> roles of the inputs it can feed
        for parameter in tool.inputs:
            for kind in kinds:
                if satisfies(kind, parameter.kind, registry):
                    roles.setdefault(kind, []).append(parameter.role)
        for kind, kind_roles in roles.items():
            edges.append(_edge(kind_ids[kind], tool_id, kind_roles))
        for output in tool.outputs:
            edges.append(_edge(tool_id, kind_ids[output.kind], [output.role]))
    return {'nodes': nodes, 'edges': edges}


def tool_node_id(identifier, is_model):
    """Id of the node of a step or model, also used to link to it (/registry/?focus=<id>)."""
    return f'{"model" if is_model else "step"}-{identifier}'


def _data_node(registry, kind, node_id, url_of):
    terms = [term for term in (kind.data, kind.format, kind.technique) if term is not None]
    return {'data': {
        'id': node_id,
        'type': 'data',
        'label': label(registry, kind.data),
        'detail': ' · '.join(label(registry, term) for term in terms[1:]),
        'terms': [{'label': label(registry, term), 'iri': str(term), 'url': url_of(term)} for term in terms],
    }}


def _tool_node(tool, url_of):
    data = {
        'id': tool_node_id(tool.identifier, tool.is_model),
        'type': 'model' if tool.is_model else 'step',
        'label': tool.name or tool.identifier,
        'url': url_of(tool.iri),
        'description': tool.description,
        'web_service': tool.web_service,
    }
    if tool.is_model:
        data['organisms'] = sorted(tool.organisms.values())
        data['antibiotics'] = sorted(tool.antibiotics)
    return {'data': data}


def _edge(source, target, roles):
    return {'data': {'id': f'{source}->{target}', 'source': source, 'target': target, 'roles': roles}}


def _kind_label(registry, kind):
    technique = label(registry, kind.technique) if kind.technique is not None else ''
    return (label(registry, kind.data), label(registry, kind.format), technique)
