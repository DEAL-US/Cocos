import os

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from core.models import TaskStatus
from .models import PredictionRun
from .services import describe_compatibility, get_sample_options, get_user_sample, is_processing, start_prediction
from .adapters.registry import list_all_antibiotics, list_all_organisms, list_registered_models

@login_required
def prediction_ui(request):
    return render(request, 'prediction/prediction.html', {
        'sample_options': get_sample_options(request.user),
        'available_models': list_registered_models(),
        'available_antibiotics': list_all_antibiotics(),
    })

@login_required
@require_POST
def make_prediction_view(request):
    model_names = request.POST.getlist('models')
    antibiotics = request.POST.getlist('antibiotics')
    sample_id = request.POST.get('sample_id', '').strip() or None
    task = None

    try:
        run = start_prediction(
            user=request.user,
            model_names=model_names,
            antibiotics=antibiotics,
            process_id=sample_id,
        )
    except ValueError as e:
        messages.error(request, str(e))
        return JsonResponse({'error': str(e)}, status=400)
    except Exception as e:
        messages.error(request, str(e))
        return JsonResponse(
            {'error': 'An unexpected error occurred while computing predictions.'},
            status=500,
        )
    
    return JsonResponse({'run_id': run.id, 'process_id': run.process.id}, status=202)

@login_required
@require_GET
def sample_models_view(request, process_id):
    """What every model can do with a sample of the user: ready, needs preparation, or not available."""
    try:
        process = get_user_sample(request.user, process_id)
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=404)
    organisms = dict(list_all_organisms())
    return JsonResponse({
        'processing': is_processing(process),
        'organism': organisms.get(process.organism, process.organism) or None,
        'models': describe_compatibility(process),
    })

@login_required
@require_POST
def download_prediction_csv(request, prediction_run_id):
    run = get_object_or_404(_get_user_prediction_runs(request.user), pk=prediction_run_id)

    if run.status != TaskStatus.COMPLETED or not run.output_csv:
        messages.error(request, 'The requested CSV is not available for download.')
        return redirect('prediction:prediction')

    try:
        file = run.output_csv.file.open('rb')
        filename = os.path.basename(run.output_csv.file.name)

        response = FileResponse(
            file,
            as_attachment=True,
            filename=filename,
            content_type='text/csv',
        )
        
        return response
    
    except Exception as e:
        messages.error(request, 'Could not read the CSV file. Please try again later.')
        return redirect('prediction:prediction')

def _get_user_prediction_runs(user):
    return PredictionRun.objects.filter(process__user=user).order_by('-created_at')