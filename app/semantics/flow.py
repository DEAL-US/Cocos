"""The registry as a data flow: which kinds of data each step and model consumes and produces.

It is drawn on the registry page. The nodes are the kinds of data (EDAM data + format, and the
sequencing technique of reads), the steps and the models. A kind of data points to every step or
model it can feed and a step points to the data it produces, decided with the same reading
(read_tools) and matching (satisfies) as the discovery, so the drawing shows the paths the
discovery can take.

The flow of a sample (sample_flow) is the same drawing with the state of the sample on it: the data
it has, what its steps did, which steps the discovery would run to prepare a model, and whether
each model is ready, needs preparation or is not available.

The result is plain data in the elements format of Cytoscape.js.
"""
from .discovery import discover
from .discovery.graphs import label, read_sample, read_tools
from .discovery.search import satisfies

# What a kind of data with no file format (the genes) is, in the drawing
STORED_BY_COCOS = 'Stored in Cocos'


def registry_flow(registry, url_of=str):
    """{'nodes': [...], 'edges': [...]} of `registry` (a graph). `url_of(iri)` gives the page of a
    step, model or ontology term."""
    return _flow(registry, url_of)[0]


def sample_flow(registry, sample, runs, url_of=str, software=None, failed=None):
    """The flow of `registry` with the state of `sample` (its graph) in the data of each node.

    `runs` is {node id: status of the latest task of that step or model} for the sample, and
    `software` {node id: labels of the software that task used}. Data nodes get `files` (ids of the
    files of the sample that are that data), steps get `state` (a task status, 'planned' or
    'unused') and `for_models` (the models whose preparation would run them), models get
    `compatibility`, `reasons` and `run`, and steps and models get `software`. `failed` are the
    steps the discovery does not plan again (see semantics.discovery.discover).
    """
    software = software or {}
    flow, kinds = _flow(registry, url_of)
    items, _ = read_sample(sample)
    results = {tool_node_id(result.model, is_model=True): result for result in discover(registry, sample, failed=failed)}
    planned = {}
    for result in results.values():
        for step in result.steps:
            planned.setdefault(tool_node_id(step.step, is_model=False), []).append(result.model)

    for node in flow['nodes']:
        data = node['data']
        if data['type'] == 'data':
            data['files'] = sorted({item.source.file for item in items if satisfies(item.kind, kinds[data['id']], registry)})
        elif data['type'] == 'step':
            data['state'] = runs.get(data['id']) or ('planned' if data['id'] in planned else 'unused')
            data['for_models'] = sorted(planned.get(data['id'], []))
            data['software'] = software.get(data['id'], [])
        else:
            result = results[data['id']]
            data['compatibility'] = result.status.value
            data['reasons'] = list(result.reasons)
            data['run'] = runs.get(data['id'])
            data['software'] = software.get(data['id'], [])
    return flow


def _flow(registry, url_of):
    """(flow, {data node id: Kind})."""
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
    return {'nodes': nodes, 'edges': edges}, {node_id: kind for kind, node_id in kind_ids.items()}


def tool_node_id(identifier, is_model):
    """Id of the node of a step or model, also used to link to it (/registry/?focus=<id>)."""
    return f'{"model" if is_model else "step"}-{identifier}'


def _data_node(registry, kind, node_id, url_of):
    terms = [term for term in (kind.data, kind.format, kind.technique) if term is not None]
    return {'data': {
        'id': node_id,
        'type': 'data',
        'label': label(registry, kind.data),
        'detail': ' · '.join(label(registry, term) for term in terms[1:]) or STORED_BY_COCOS,
        'terms': [{'label': label(registry, term), 'iri': str(term), 'url': url_of(term)} for term in terms],
    }}


def _tool_node(tool, url_of):
    data = {
        'id': tool_node_id(tool.identifier, tool.is_model),
        'type': 'model' if tool.is_model else 'step',
        'label': tool.name or tool.identifier,
        'identifier': tool.identifier,
        'url': url_of(tool.iri),
        'description': tool.description,
        'web_service': tool.web_service,
    }
    if tool.is_model:
        data['organisms'] = sorted(tool.organisms.values())
        data['antibiotics'] = sorted(tool.antibiotics)
        data['antibiotics_number'] = len(tool.antibiotics)
    return {'data': data}


def _edge(source, target, roles):
    return {'data': {'id': f'{source}->{target}', 'source': source, 'target': target, 'roles': roles}}


def _kind_label(registry, kind):
    return tuple(label(registry, term) if term is not None else '' for term in (kind.data, kind.format, kind.technique))
