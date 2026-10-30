import os

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.pagination import get_pagination_page_range
from core.utils import create_file_zip
from core.models import ProcessGroup, TaskStatus
from ..services.status import (
    build_process_rows,
    build_process_status_context,
    get_fastq_uploads_for_task,
    get_fasta_upload_for_task,
    get_json_upload_for_task,
    get_process_files,
    rename_process,
    set_process_organism,
)
from ..models import ConversionTask


def get_current_user_tasks(request):
    """Return tasks filtered by authenticated user."""
    return ConversionTask.objects.filter(process__user=request.user)


@login_required
def process_list_view(request):
    """Render process rows for conversion tasks."""
    rows = build_process_rows(request.user)
    paginator = Paginator(rows, 3)
    page_obj = paginator.get_page(request.GET.get('page', 1))
    
    return render(request, 'conversion/process_list.html', {
        'page_obj': page_obj,
        'pagination_page_range': get_pagination_page_range(paginator, page_obj.number),
        'pagination_url': reverse('conversion:process_list'),
        'pagination_query': '',
        'pagination_label': 'Samples',
        'pagination_link_attribute': 'data-process-page',
    })

@login_required
def process_status_view(request, process_id):
    # Another user's process is reported exactly like a missing one, so ids cannot be probed.
    process = ProcessGroup.objects.filter(id=process_id, user=request.user).first()

    if not process:
        messages.error(request, 'Sample not found.')
        return redirect('conversion:process_list')

    context = build_process_status_context(process, page=request.GET.get('page'))

    return render(request, 'conversion/process_status.html', context)


@login_required
def download_json_view(request, task_id):
    task = get_object_or_404(get_current_user_tasks(request), id=task_id)

    if task.status != TaskStatus.COMPLETED:
        return redirect('conversion:process_status', process_id=task.process.id)

    upload = get_json_upload_for_task(task)

    if not upload:
        messages.error(request, 'JSON file is not available for download.')
        return redirect('conversion:process_status', process_id=task.process.id)

    try:
        file = upload.file.open('rb')
        filename = os.path.basename(upload.file.name)

        response = FileResponse(
            file,
            as_attachment=True,
            filename=filename,
            content_type='application/json',
        )
        return response

    except Exception:
        messages.error(request,'Could not read the JSON file. Please try again later.')
        return redirect('conversion:process_status', process_id=task.process.id)

@login_required
def download_fasta_view(request, task_id):
    task = get_object_or_404(get_current_user_tasks(request), id=task_id)

    if task.status != TaskStatus.COMPLETED:
        return redirect('conversion:process_status', process_id=task.process.id)

    upload = get_fasta_upload_for_task(task)

    if not upload:
        messages.error(request, 'FASTA file is not available for download.')
        return redirect('conversion:process_status', process_id=task.process.id)

    try:
        file = upload.file.open('rb')
        filename = os.path.basename(upload.file.name)

        response = FileResponse(
            file,
            as_attachment=True,
            filename=filename,
            content_type='application/octet-stream',
        )
        return response

    except Exception:
        messages.error(request, 'Could not read the FASTA file. Please try again later.')
        return redirect('conversion:process_status', process_id=task.process.id)

@login_required
def download_fastq_view(request, task_id):
    task = get_object_or_404(get_current_user_tasks(request), id=task_id)

    uploads = get_fastq_uploads_for_task(task)

    if not uploads.exists():
        messages.error(request, 'FASTQ files are not available for download.')
        return redirect('conversion:process_status', process_id=task.process.id)

    try:
        zip_path = create_file_zip(uploads)

        return FileResponse(
            open(zip_path, 'rb'),
            as_attachment=True,
            filename=f'{task.process.name}_fastq.zip',
            content_type='application/zip',
        )

    except Exception:
        messages.error(request, 'Could not read the FASTQ files. Please try again later.')
        return redirect('conversion:process_status', process_id=task.process.id)
    
@login_required
def download_process_file_view(request, process_id, file_id):
    """Download one file consumed or produced by a process of the user, exactly as stored."""
    process = get_object_or_404(ProcessGroup, id=process_id, user=request.user)
    file = get_object_or_404(get_process_files(process), id=file_id)
    return FileResponse(file.file.open('rb'), as_attachment=True, filename=os.path.basename(file.file.name))


@require_POST
@login_required
def set_organism_view(request, process_id):
    process = get_object_or_404(ProcessGroup, id=process_id, user=request.user)
    try:
        set_process_organism(process, (request.POST.get('organism') or '').strip())
        messages.success(request, 'Organism updated.')
    except ValueError as e:
        messages.error(request, str(e))
    return redirect('conversion:process_status', process_id=process.id)


@require_POST
@login_required
def rename_process_view(request, process_id):
    process = get_object_or_404(ProcessGroup, id=process_id, user=request.user)
    new_name = (request.POST.get('process_name') or '').strip()
    if not new_name:
        messages.error(request, 'Sample name cannot be empty.')
        return redirect('conversion:process_status', process_id=process.id)

    rename_process(process, new_name)
    messages.success(request, 'Sample name updated.')
    return redirect('conversion:process_status', process_id=process.id)
