"""A prediction as an RO-Crate (https://w3id.org/ro/crate): a zip with its files and their
description in ro-crate-metadata.json (JSON-LD, schema.org), following the Process Run Crate
profile, so that other tools (WorkflowHub, Galaxy, Zenodo...) can read how it was obtained.

It is built from the provenance of the sample (semantics.provenance), with SPARQL: each activity
that led to the prediction, followed back from the predictions of its models to what the user
uploaded, is a CreateAction with the software that ran it (instrument), what it used (object) and
what it generated (result). Building the matrix of the prediction from the result of each model is
one more action. The crate has every file of those steps, from the reads to the matrix, and Cocos's
own description of the sample (provenance.ttl, with the trust of the predictions).

RO-Crate 1.1 and Process Run Crate 0.5 are the versions the validator (roc-validator) implements.
"""
import json
import os
import zipfile

from django.conf import settings
from django.utils import timezone
from rdflib import URIRef
from rdflib.namespace import PROV

from core.models import File

from .namespaces import PREFIXES, SCHEMA

RO_CRATE = 'https://w3id.org/ro/crate/1.1'
PROCESS_RUN_CRATE = 'https://w3id.org/ro/wfrun/process/0.5'
METADATA_FILE = 'ro-crate-metadata.json'
PROVENANCE_FILE = 'provenance.ttl'
USER = '#user'
# RO-Crate 1.1 requires a license; the data belongs to the user, so Cocos does not choose one
LICENSE = {
    '@id': '#license',
    '@type': 'CreativeWork',
    'name': 'No license set',
    'description': ('The data of this crate belongs to the user who uploaded it to Cocos, who decides how it can '
                    'be used. Reads of clinical isolates may contain traces of human DNA.'),
}
PREDICTION_FORMAT = URIRef('http://edamontology.org/format_3752')  # CSV of the matrix
# Files that are compressed already (e.g. the reads) are stored in the zip as they are
COMPRESSED = ('.gz', '.zip', '.bz2', '.xz')

# Query to get activities that led to the prediction, from the predictions of its models back to what the user uploaded
UPSTREAM = 'SELECT DISTINCT ?activity WHERE { ?prediction (prov:used/prov:wasGeneratedBy)* ?activity }'

# Query to get details of an activity
ACTIVITY = """
SELECT ?name ?status ?start ?end ?error WHERE {
    OPTIONAL { ?activity schema:name ?name }
    OPTIONAL { ?activity schema:actionStatus ?status }
    OPTIONAL { ?activity prov:startedAtTime ?start }
    OPTIONAL { ?activity prov:endedAtTime ?end }
    OPTIONAL { ?activity schema:error ?error }
}"""

# Query to get the software that ran an activity
SOFTWARE = """
SELECT ?agent ?name ?version ?url WHERE {
    ?activity prov:wasAssociatedWith ?agent .
    ?agent a prov:SoftwareAgent ; schema:name ?name ; schema:softwareVersion ?version .
    OPTIONAL { ?agent prov:specializationOf ?url }
}"""

# What an activity used that is not data of the sample: databases (by DOI) and weights (by SHA-256)
REFERENCES = """
SELECT ?entity ?label ?name ?version ?sha256 WHERE {
    ?activity prov:used ?entity .
    ?entity a prov:Entity .
    FILTER NOT EXISTS { ?entity schema:identifier ?file }
    OPTIONAL { ?entity rdfs:label ?label }
    OPTIONAL { ?entity schema:name ?name }
    OPTIONAL { ?entity schema:version ?version }
    OPTIONAL { ?entity schema:sha256 ?sha256 }
}"""

# The data an activity used or generated
DATA = """
SELECT ?entry ?file ?role ?format WHERE {
    { ?activity prov:used ?entry } UNION { ?entry prov:wasGeneratedBy ?activity }
    ?entry schema:identifier ?file ; schema:name ?role .
    OPTIONAL { ?entry schema:encodingFormat ?format }
}"""


def prediction_crate(run, graph, sample):
    """(ro-crate-metadata.json as a dict, {path in the crate: File}) of the prediction `run`.
    `graph` is the RDF of its process with its provenance, whose IRI is `sample`."""
    # What is found, once each: {activity: action}, {@id: entity}, {path: File}, {file id: @id}
    crate = {'graph': graph, 'sample': str(sample), 'actions': {}, 'entities': {}, 'files': {}, 'file_ids': {}}
    tasks = list(run.tasks.order_by('id'))
    for task in tasks:
        for activity in _query(graph, UPSTREAM, prediction=URIRef(f'{sample}#task-{task.pk}')):
            if activity not in crate['actions']:
                crate['actions'][activity] = _action(crate, activity)
    actions = sorted(crate['actions'].values(), key=lambda action: action.get('startTime', ''))
    if run.output_csv is not None:
        actions.append(_matrix_action(crate, run, tasks))

    root = {
        '@id': './',
        '@type': 'Dataset',
        'name': f'Prediction of {run.process.name}',
        'description': (f'Antibiotic resistance prediction made with Cocos {settings.COCOS_VERSION} on '
                        f'{run.created_at:%Y-%m-%d}: the models {", ".join(run.selected_models)} for '
                        f'{", ".join(run.selected_antibiotics)}, with the files and steps that led to it.'),
        'datePublished': timezone.now().isoformat(),
        'conformsTo': {'@id': PROCESS_RUN_CRATE},
        'license': {'@id': LICENSE['@id']},
        'hasPart': [{'@id': path} for path in [*crate['files'], PROVENANCE_FILE]],
        'mentions': [{'@id': action['@id']} for action in actions],
    }
    provenance = {
        '@id': PROVENANCE_FILE,
        '@type': 'File',
        'name': 'Provenance of the sample',
        'description': ('Everything Cocos knows about the sample, in RDF: its data, the steps that were run '
                        '(PROV-O, P-Plan) and the trust of its predictions (DQV).'),
        'encodingFormat': 'text/turtle',
        'conformsTo': {'@id': str(PROV)},
    }
    entities = [
        {'@id': METADATA_FILE, '@type': 'CreativeWork', 'conformsTo': {'@id': RO_CRATE}, 'about': {'@id': './'}},
        root,
        {'@id': PROCESS_RUN_CRATE, '@type': 'CreativeWork', 'name': 'Process Run Crate', 'version': '0.5'},
        {'@id': USER, '@type': 'Person', 'name': 'A user of this Cocos instance'},
        LICENSE,
        *actions, *crate['entities'].values(), provenance,
    ]
    # The checksums of the files (schema:sha256) are not in the context of RO-Crate 1.1
    context = [f'{RO_CRATE}/context', {'sha256': 'http://schema.org/sha256'}]
    return {'@context': context, '@graph': entities}, crate['files']


def write_crate(zip_file, metadata, files, provenance):
    """Write the crate to `zip_file` (a zipfile.ZipFile): its description, files and provenance (Turtle).
    Files are copied in chunks, and those compressed already are stored as they are."""
    zip_file.writestr(METADATA_FILE, json.dumps(metadata, indent=2, ensure_ascii=False))
    zip_file.writestr(PROVENANCE_FILE, provenance)
    for path, file in files.items():
        # The date of the file in Cocos (without it, the zip says 1980, the earliest date it can store)
        info = zipfile.ZipInfo(path, date_time=timezone.localtime(file.created_at).timetuple()[:6])
        info.compress_type = zipfile.ZIP_STORED if path.endswith(COMPRESSED) else zipfile.ZIP_DEFLATED
        with file.file.open('rb') as content, zip_file.open(info, 'w', force_zip64=True) as target:
            for chunk in iter(lambda: content.read(1024 * 1024), b''):
                target.write(chunk)


# --- The entities of the crate

def _action(crate, activity):
    """The CreateAction of an activity: the software that ran it (instrument), what it used
    (object: data, databases, weights) and what it generated (result)."""
    graph = crate['graph']
    action = {'@id': _local(crate, activity), '@type': 'CreateAction', 'agent': {'@id': USER}}
    row = next(iter(_query(graph, ACTIVITY, activity=activity, rows=True)), None)
    if row is not None:
        for key, value in (('name', row.name), ('startTime', row.start), ('endTime', row.end), ('error', row.error)):
            if value is not None:
                action[key] = str(value)
        if row.status is not None:  # the context of RO-Crate uses http://schema.org/
            action['actionStatus'] = {'@id': str(row.status).replace(str(SCHEMA), 'http://schema.org/')}
    action['instrument'] = [{'@id': _software(crate, row)} for row in _query(graph, SOFTWARE, activity=activity, rows=True)]
    objects, results = [], []
    for row in _query(graph, DATA, activity=activity, rows=True):
        generated = (row.entry, PROV.wasGeneratedBy, activity) in graph
        (results if generated else objects).append({'@id': _data(crate, row)})
    objects += [{'@id': _reference(crate, row)} for row in _query(graph, REFERENCES, activity=activity, rows=True)]
    if objects:
        action['object'] = objects
    if results:
        action['result'] = results
    return action


def _matrix_action(crate, run, tasks):
    """The action that built the matrix of the prediction from the result of each model."""
    models = [f'{crate["sample"]}#task-{task.pk}' for task in tasks]
    results = [entity for activity, action in crate['actions'].items() if str(activity) in models
               for entity in action.get('result', [])]
    cocos = f'#software-cocos-{settings.COCOS_VERSION}'
    crate['entities'].setdefault(cocos, {'@id': cocos, '@type': 'SoftwareApplication', 'name': 'Cocos',
                                         'softwareVersion': settings.COCOS_VERSION})
    return {
        '@id': f'#run-{run.pk}',
        '@type': 'CreateAction',
        'name': 'Prediction matrix',
        'agent': {'@id': USER},
        'instrument': [{'@id': cocos}],
        'object': results,
        'result': [{'@id': _file(crate, run.output_csv, PREDICTION_FORMAT)}],
        'endTime': run.updated_at.isoformat(),
        'actionStatus': {'@id': 'http://schema.org/CompletedActionStatus'},
    }


def _software(crate, row):
    """A SoftwareApplication, with its version and its page (e.g. in bio.tools)."""
    entity_id = _local(crate, row.agent)
    entity = {'@id': entity_id, '@type': 'SoftwareApplication', 'name': str(row.name), 'softwareVersion': str(row.version)}
    if row.url is not None:
        entity['url'] = str(row.url)
    crate['entities'].setdefault(entity_id, entity)
    return entity_id


def _reference(crate, row):
    """A database (identified by its DOI) or the weights of a model (by their SHA-256)."""
    entity_id = _local(crate, row.entity)
    entity = {'@id': entity_id, '@type': 'CreativeWork', 'name': str(row.label or row.name or entity_id)}
    if row.version is not None and str(row.version):
        entity['version'] = str(row.version)
    if row.sha256 is not None:
        entity['sha256'] = str(row.sha256)
    crate['entities'].setdefault(entity_id, entity)
    return entity_id


def _data(crate, row):
    """A piece of data of the sample: its file or, for the genes Cocos keeps in its database (no
    format), an entity based on the file they come from."""
    file = File.objects.get(pk=int(row.file))
    file_id = _file(crate, file, row.format)
    if row.format is not None:
        return file_id
    entity_id = f'#genes-{file.pk}'
    crate['entities'].setdefault(entity_id, {
        '@id': entity_id, '@type': 'CreativeWork', 'name': f'Genes of {os.path.basename(file.file.name)}',
        'description': 'The genes Cocos extracted from this annotation; it keeps them in its database.',
        'isBasedOn': {'@id': file_id},
    })
    return entity_id


def _file(crate, file, file_format=None):
    """A file of the crate, under its own name (with a number if another file has it)."""
    if file.pk in crate['file_ids']:  # e.g. a Bakta JSON, as the annotation and as the source of the genes
        entity_id = crate['file_ids'][file.pk]
        if file_format is not None:
            crate['entities'][entity_id].setdefault('encodingFormat', {'@id': str(file_format)})
        return entity_id
    name = os.path.basename(file.file.name)
    entity_id = _free_path(crate['files'], name)
    crate['files'][entity_id] = file
    entity = {'@id': entity_id, '@type': 'File', 'name': name}
    if file.sha256:
        entity['sha256'] = file.sha256
    if file_format is not None:
        entity['encodingFormat'] = {'@id': str(file_format)}
    crate['entities'][entity_id] = entity
    crate['file_ids'][file.pk] = entity_id
    return entity_id


def _free_path(files, name):
    """`name`, or 'reads-2.fastq.gz', 'reads-3.fastq.gz'... if a file of the crate has it already."""
    stem, extension = name.split('.', 1) if '.' in name else (name, '')
    path, number = name, 2
    while path in files:
        path, number = f'{stem}-{number}.{extension}' if extension else f'{stem}-{number}', number + 1
    return path


def _local(crate, iri):
    """'#task-3' for <sample#task-3>."""
    return str(iri).removeprefix(crate['sample'])


def _query(graph, text, rows=False, **bindings):
    result = graph.query(text, initNs=PREFIXES, initBindings=bindings)
    return list(result) if rows else [row[0] for row in result]
