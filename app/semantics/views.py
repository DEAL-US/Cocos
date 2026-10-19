"""RDF views: the description of a sample (private, for its owner) and the public registry.

The registry is public: a read-only SPARQL endpoint over it, and a page for each step, model,
AMRF term and the shapes, so that their IRIs (https://w3id.org/cocos/..., https://w3id.org/amrf/...)
resolve once w3id redirects them here. Browsers get HTML; RDF clients get Turtle or JSON-LD.
"""
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from pyparsing import ParseException
from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import RDF, RDFS
from rdflib.plugins.sparql import prepareQuery
from rdflib.plugins.sparql.parserutils import CompValue

from core.models import ProcessGroup

from .namespaces import AMRF, COCOS, PREFIXES, SCHEMA, bind_prefixes
from .registry.graph import registry_graph
from .registry.vocabulary import load_vocabulary
from .sample import sample_graph
from .validation import shapes_graph

JSON_LD = 'application/ld+json'
TURTLE = 'text/turtle'
RDF_FORMATS = {'turtle': TURTLE, 'json-ld': JSON_LD}
RESULT_FORMATS = {  # SELECT and ASK results, by media type
    'application/sparql-results+json': 'json',
    'application/sparql-results+xml': 'xml',
    'text/csv': 'csv',
}
MAX_QUERY_LENGTH = 10_000


# --- Content negotiation

def rdf_format(request, default='turtle'):
    """'turtle', 'json-ld' or 'html', from ?format= or the Accept header."""
    requested = request.GET.get('format')
    accept = request.headers.get('Accept', '')
    if requested in ('ttl', 'turtle') or TURTLE in accept:
        return 'turtle'
    if requested in ('jsonld', 'json-ld') or JSON_LD in accept:
        return 'json-ld'
    if requested == 'html' or (requested is None and 'text/html' in accept):
        return 'html'
    return default


def rdf_response(graph, rdf_format):
    response = HttpResponse(graph.serialize(format=rdf_format), content_type=f'{RDF_FORMATS[rdf_format]}; charset=utf-8')
    response['Access-Control-Allow-Origin'] = '*'
    return response


# --- The sample, for its owner

@login_required
def process_rdf_view(request, process_id):
    """The RDF description of a process of the user: Turtle, or JSON-LD if the client asks for it."""
    process = get_object_or_404(ProcessGroup, id=process_id, user=request.user)
    graph = sample_graph(
        process,
        sample_iri=request.build_absolute_uri(reverse('conversion:process_status', args=[process.id])),
        content_url=lambda file: request.build_absolute_uri(reverse('conversion:process_file', args=[process.id, file.id])),
    )
    rdf = rdf_format(request)
    return rdf_response(graph, 'turtle' if rdf == 'html' else rdf)


# --- The public registry: SPARQL endpoint

@csrf_exempt
def sparql_view(request):
    """Read-only SPARQL endpoint over the registry (SPARQL 1.1 protocol: GET ?query= or POST).

    SELECT and ASK results are JSON (default), XML or CSV; CONSTRUCT and DESCRIBE results are
    Turtle (default) or JSON-LD. The usual prefixes (schema, edam, obo, amrf...) are predefined.
    Updates, SERVICE (queries to other endpoints) and queries over MAX_QUERY_LENGTH are refused.
    """
    if request.method == 'OPTIONS':
        return _cors(HttpResponse())
    if request.method == 'GET':
        query = request.GET.get('query', '')
    elif request.method == 'POST':
        is_raw = request.content_type == 'application/sparql-query'
        query = request.body.decode('utf-8') if is_raw else request.POST.get('query', '')
    else:
        return _cors(HttpResponse(status=405))

    if not query.strip():
        return _error('Missing query. Send it as ?query=... or in a POST.')
    if len(query) > MAX_QUERY_LENGTH:
        return _error(f'The query is longer than {MAX_QUERY_LENGTH} characters.')
    try:
        prepared = prepareQuery(query, initNs=PREFIXES)
    except ParseException as error:
        return _error(f'Not a valid SPARQL query (updates are not accepted): {error}')
    if _uses_service(prepared.algebra):
        return _error('SERVICE (queries to other endpoints) is not allowed.')

    result = registry_graph().query(prepared)
    accept = request.headers.get('Accept', '')
    if result.type in ('SELECT', 'ASK'):
        media_type = next((media for media in RESULT_FORMATS if media in accept), 'application/sparql-results+json')
        return _cors(HttpResponse(result.serialize(format=RESULT_FORMATS[media_type]), content_type=f'{media_type}; charset=utf-8'))
    graph = bind_prefixes(Graph()) + result.graph
    return rdf_response(graph, 'json-ld' if JSON_LD in accept else 'turtle')


def _uses_service(node):
    if isinstance(node, CompValue):
        return node.name == 'ServiceGraphPattern' or any(_uses_service(value) for value in node.values())
    if isinstance(node, (list, tuple)):
        return any(_uses_service(value) for value in node)
    return False


def _cors(response):
    response['Access-Control-Allow-Origin'] = '*'
    response['Access-Control-Allow-Headers'] = 'Content-Type, Accept'
    response['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    return response


def _error(message):
    return _cors(HttpResponse(message, status=400, content_type='text/plain; charset=utf-8'))


# --- The public registry: one page per resource

def registry_view(request):
    """The whole registry: an index of its steps and models, or all of it as RDF."""
    graph = registry_graph()
    rdf = rdf_format(request, default='html')
    if rdf != 'html':
        return rdf_response(graph, rdf)
    tools = sorted(
        ({'name': str(graph.value(tool, SCHEMA.name) or tool),
          'description': str(graph.value(tool, SCHEMA.description) or ''),
          'url': local_url(tool),
          'is_model': str(tool).startswith(str(COCOS['model/']))}
         for tool in graph.subjects(RDF.type, SCHEMA.SoftwareApplication)),
        key=lambda tool: tool['name'],
    )
    return render(request, 'semantics/registry.html', {'sections': [
        ('Processing steps', 'bi-diagram-3', [tool for tool in tools if not tool['is_model']]),
        ('Prediction models', 'bi-cpu', [tool for tool in tools if tool['is_model']]),
    ]})


def step_view(request, key):
    return _resource(request, registry_graph(), COCOS[f'step/{key}'])


def model_view(request, name):
    return _resource(request, registry_graph(), COCOS[f'model/{name}'])


def vocabulary_view(request):
    """The AMRF vocabulary: its header and every term."""
    vocabulary = load_vocabulary()
    rdf = rdf_format(request, default='html')
    if rdf != 'html':
        return rdf_response(vocabulary, rdf)
    terms = sorted(set(vocabulary.subjects()) - {URIRef(str(AMRF))}, key=str)
    return render(request, 'semantics/resource.html', {
        'title': 'AMRF: AntiMicrobial Resistance Framework vocabulary',
        'iri': str(AMRF),
        'filename': 'amrf',
        'subjects': [_subject(vocabulary, URIRef(str(AMRF)))] + [_subject(vocabulary, term) for term in terms],
    })


def vocabulary_term_view(request, term):
    return _resource(request, load_vocabulary(), AMRF[term])


def shapes_view(request):
    """The AMRF SHACL shapes: the Turtle, also in the browser."""
    rdf = rdf_format(request, default='html')
    if rdf != 'html':
        return rdf_response(shapes_graph(), rdf)
    return render(request, 'semantics/resource.html', {
        'title': 'AMRF shapes', 'iri': str(AMRF) + 'shapes', 'filename': 'amrf-shapes',
        'turtle': bind_prefixes(Graph() + shapes_graph()).serialize(format='turtle'),
    })


def _resource(request, graph, iri):
    description = describe(graph, iri)
    if not len(description):
        raise Http404(f'{iri} is not in the registry')
    rdf = rdf_format(request, default='html')
    if rdf != 'html':
        return rdf_response(description, rdf)
    subjects = [iri] + sorted({s for s in description.subjects() if s != iri and isinstance(s, URIRef)}, key=str)
    return render(request, 'semantics/resource.html', {
        'title': str(graph.value(iri, SCHEMA.name) or graph.value(iri, RDFS.label) or iri),
        'iri': str(iri),
        'filename': str(iri).rstrip('/').rsplit('/', 1)[-1],
        'subjects': [_subject(graph, subject) for subject in subjects],
    })


def describe(graph, iri):
    """The triples about `iri`, its parts (IRIs `iri#...`, such as its inputs) and its blank nodes."""
    description = bind_prefixes(Graph())
    pending, seen = [iri], set()
    while pending:
        node = pending.pop()
        if node in seen:
            continue
        seen.add(node)
        for triple in graph.triples((node, None, None)):
            description.add(triple)
            value = triple[2]
            if isinstance(value, BNode) or str(value).startswith(f'{iri}#'):
                pending.append(value)
    return description


def _subject(graph, subject):
    """A subject and its properties, ready for the template."""
    names = graph.namespace_manager
    properties = {}
    for predicate, value in sorted(graph.predicate_objects(subject), key=lambda pair: (str(pair[0]), str(pair[1]))):
        properties.setdefault(names.normalizeUri(predicate), []).append(_value(graph, value))
    return {'iri': str(subject), 'fragment': str(subject).partition('#')[2], 'properties': properties}


def _value(graph, value):
    if isinstance(value, Literal):
        return {'text': str(value)}
    if isinstance(value, BNode):
        return {'text': ', '.join(str(o) for o in graph.objects(value, SCHEMA.name)) or 'blank node'}
    label = graph.value(value, RDFS.label) or registry_graph().value(value, RDFS.label)
    return {'text': str(label) if label else graph.namespace_manager.normalizeUri(value),
            'iri': str(value), 'url': local_url(value)}


def local_url(iri):
    """The page of this server for a registry IRI (what w3id will redirect to), or the IRI itself."""
    iri = str(iri)
    for namespace, prefix in ((str(COCOS), '/'), (str(AMRF), '/amrf/')):
        if iri.startswith(namespace):
            return prefix + iri[len(namespace):]
    return iri
