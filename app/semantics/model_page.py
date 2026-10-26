"""What the page of a model in the registry shows, read from its descriptor with SPARQL: how it was
built (PROV-O), how well it works and how much data it had (DQV), and the files it depends on.

Every part is optional, so that the page works for any model, whatever its descriptor declares.
"""
from .namespaces import DQV, OBO, PREFIXES
from .registry.terms import terms_graph

SAMPLE_SIZE = OBO.NCIT_C53190
PROPORTION = OBO.STATO_0000607

BUILT_FROM = """
SELECT ?data ?name ?description ?dataset ?license ?agentLabel ?tool ?usedLabel WHERE {
    ?model prov:wasDerivedFrom ?data .
    OPTIONAL { ?data schema:name ?name }
    OPTIONAL { ?data schema:description ?description }
    OPTIONAL { ?data schema:isPartOf ?dataset }
    OPTIONAL { ?data schema:license ?license }
    OPTIONAL {
        ?data prov:wasGeneratedBy ?activity .
        OPTIONAL { ?activity prov:wasAssociatedWith ?agent . ?agent rdfs:label ?agentLabel .
                   OPTIONAL { ?agent prov:specializationOf ?tool } }
        OPTIONAL { ?activity prov:used ?used . ?used rdfs:label ?usedLabel }
    }
}"""

MEASUREMENTS = """
SELECT ?measurement ?metric ?value ?data ?dataLabel ?dataDescription WHERE {
    ?model dqv:hasQualityMeasurement ?measurement .
    ?measurement dqv:isMeasurementOf ?metric ; dqv:value ?value ; dqv:computedOn ?data .
    OPTIONAL { ?data rdfs:label ?dataLabel }
    OPTIONAL { ?data dcterms:description ?dataDescription }
}"""

FILES = """
SELECT ?name ?sha256 WHERE { ?model schema:hasPart ?file . ?file schema:name ?name ; schema:sha256 ?sha256 . }
ORDER BY ?name"""


def model_page(graph, model):
    """{'built_from': [...], 'metrics': [...], 'antibiotics': [...], 'files': [...]} of `model`."""
    return {
        'built_from': built_from(graph, model),
        **measurements(graph, model),
        'files': [{'name': str(row.name), 'sha256': str(row.sha256)}
                  for row in graph.query(FILES, initNs=PREFIXES, initBindings={'model': model})],
    }


def built_from(graph, model):
    """The data the model was built from, and what it was prepared with."""
    sources = {}
    for row in graph.query(BUILT_FROM, initNs=PREFIXES, initBindings={'model': model}):
        source = sources.setdefault(row.data, {
            'name': str(row.name or ''), 'description': str(row.description or ''),
            'dataset': str(row.dataset or ''), 'license': str(row.license or ''),
            'prepared_with': {}, 'used': set(),
        })
        if row.agentLabel is not None:
            source['prepared_with'][str(row.agentLabel)] = str(row.tool or '')
        if row.usedLabel is not None:
            source['used'].add(str(row.usedLabel))
    return [{**source, 'prepared_with': sorted(source['prepared_with'].items()), 'used': sorted(source['used'])}
            for source in sources.values()]


def measurements(graph, model):
    """The measurements of the model: `metrics`, those about the whole model (e.g. its F1 score),
    and `antibiotics`, the number of isolates and percentage of resistant ones of its data for each
    antibiotic, with a row for each species."""
    metrics, antibiotics = [], {}
    for row in graph.query(MEASUREMENTS, initNs=PREFIXES, initBindings={'model': model}):
        about = set(graph.objects(row.measurement, OBO.IAO_0000136))
        drugs = {term for term in about if str(term).startswith(str(OBO) + 'ARO_')}
        taxa = sorted(about - drugs, key=str)
        if not about:
            metrics.append({'metric': _label(row.metric), 'value': row.value.toPython(),
                            'computed_on': str(row.dataLabel or ''), 'description': str(row.dataDescription or '')})
            continue
        if len(drugs) != 1 or row.metric not in (SAMPLE_SIZE, PROPORTION):
            continue
        drug = antibiotics.setdefault(next(iter(drugs)), {'antibiotic': _label(next(iter(drugs))), 'species': {}})
        target = drug if not taxa else drug['species'].setdefault(tuple(taxa), {
            'species': ' / '.join(_label(taxon) for taxon in taxa)})
        if row.metric == SAMPLE_SIZE:
            target['isolates'] = int(row.value.toPython())
        else:
            target['resistant_percent'] = round(float(row.value.toPython()) * 100, 1)
    rows = []
    for drug in sorted(antibiotics.values(), key=lambda drug: drug['antibiotic']):
        species = sorted(drug.pop('species').values(), key=lambda row: -row.get('isolates', 0))
        rows.append({**drug, 'species': species})
    return {'metrics': sorted(metrics, key=lambda metric: metric['metric']), 'antibiotics': rows}


def _label(term):
    label = terms_graph().value(term, PREFIXES['rdfs'].label)
    return str(label) if label is not None else str(term).rsplit('/', 1)[-1]
