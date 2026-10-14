from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from prediction.adapters.registry import list_all_organisms
from ..services.pipeline import (
    get_assembly_tasks_can_be_annotated, 
    start_annotation_from_assembly_task, 
    start_annotation_from_uploaded_fasta, 
    start_assembly, 
    start_json_processing
)

def _annotation_context(request, active_tab='fasta', **extra):
    context = {
        'active_tab': active_tab,
        'available_fasta_jobs': get_assembly_tasks_can_be_annotated(request.user),
        'organism_options': list_all_organisms(),
    }
    context.update(extra)
    return context


@login_required
def assembly_ui(request):
    """Render Assembly workflow page (FASTQ to FASTA)."""
    return render(request, 'conversion/assembly.html', {'organism_options': list_all_organisms()})

@require_POST
@login_required
def start_assembly_task(request):
    """
    Allow users to upload a FASTQ file via a simple web form to start an external assembly task.
    On submission, create a ConversionTask and trigger polling of its status.
    """

    assembly_type = request.POST.get('assembly_type')
    annotate = request.POST.get('annotate') == 'on'
    complete_version = request.POST.get('complete') == 'on'

    fastq = request.FILES.get('fastq_file')
    fastq_2 = request.FILES.get('fastq_file_2')

    try:
        process = start_assembly(
            user=request.user,
            assembly_type=assembly_type,
            fastq=fastq,
            fastq_2=fastq_2,
            annotate=annotate,
            complete_version=complete_version,
            organism=request.POST.get('organism', ''),
        )
    except ValueError as e:
        messages.error(request, str(e))
        return redirect('conversion:assembly_ui')

    message = (f"Assembly task started for file {fastq.name}. You will be notified when it's complete.")
    messages.info(request, message)

    return redirect('conversion:process_status', process_id=process.id)


@login_required
def annotation_ui(request):
    """Render Annotation workflow page with FASTA and JSON tabs."""
    return render(request, 'conversion/annotation.html', _annotation_context(request, active_tab='fasta'))

@require_POST
@login_required
def start_annotation_task(request):
    """
    Allow users to upload a FASTA file via a simple web form to start an external annotation task.
    On submission, create an AnnotationTask and trigger polling of its status.
    """
    source_task_id = (request.POST.get('source_task_id') or '').strip()
    fasta = request.FILES.get('fasta_file')
    complete_version = request.POST.get('complete') == 'on'

    try:
        if source_task_id:
            process = start_annotation_from_assembly_task(request.user, source_task_id, complete_version,)
            message = (f'Annotation task started from previous assembly job {source_task_id}. You will be notified when it is complete.')
        else:
            process = start_annotation_from_uploaded_fasta(request.user, fasta, complete_version, organism=request.POST.get('organism', ''))
            message = (f'Annotation task started for file {fasta.name}. You will be notified when it is complete.')

    except ValueError as e:
        messages.error(request, str(e))
        return render(request, 'conversion/annotation.html', _annotation_context(request, active_tab='fasta'))

    messages.info(request, message)

    return redirect('conversion:process_status', process_id=process.id)

@require_POST
@login_required
def parse_feature_file(request):
    """Start Bakta JSON processing from the Annotation tab."""

    feature_file = request.FILES.get('feature_file')
    complete_version = request.POST.get('complete') == 'on'

    try:
        process = start_json_processing(
            user=request.user,
            feature_file=feature_file,
            complete_version=complete_version,
            organism=request.POST.get('organism', ''),
        )

    except ValueError as e:
        messages.error(request, str(e))
        return render(request, 'conversion/annotation.html', _annotation_context(request, active_tab='json'))

    messages.info(request, f"JSON processing started for {feature_file.name}. You will be notified when it is complete.")

    return redirect('conversion:process_status', process_id=process.id)

