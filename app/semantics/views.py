from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse

from core.models import ProcessGroup

from .sample import sample_graph

JSON_LD = 'application/ld+json'
TURTLE = 'text/turtle'


@login_required
def process_rdf_view(request, process_id):
    """The RDF description of a process of the user: Turtle, or JSON-LD if the client asks for it."""
    process = get_object_or_404(ProcessGroup, id=process_id, user=request.user)
    graph = sample_graph(
        process,
        sample_iri=request.build_absolute_uri(reverse('conversion:process_status', args=[process.id])),
        content_url=lambda file: request.build_absolute_uri(reverse('conversion:process_file', args=[process.id, file.id])),
    )
    if request.GET.get('format') == 'jsonld' or JSON_LD in request.headers.get('Accept', ''):
        return HttpResponse(graph.serialize(format='json-ld'), content_type=f'{JSON_LD}; charset=utf-8')
    return HttpResponse(graph.serialize(format='turtle'), content_type=f'{TURTLE}; charset=utf-8')
