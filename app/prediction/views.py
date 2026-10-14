import os

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.models import TaskStatus
from .models import PredictionRun
from .services import get_prediction_input_options, start_prediction
from .adapters.registry import list_registered_models, list_all_antibiotics

@login_required
def prediction_ui(request):
    return render(request, 'prediction/prediction.html', {
        'input_file_options': get_prediction_input_options(request.user),
        'available_models': list_registered_models(),
        'available_antibiotics': list_all_antibiotics(),
    })

@login_required
@require_POST
def make_prediction_view(request):
    model_names = request.POST.getlist('models')
    antibiotics = request.POST.getlist('antibiotics')
    file_id = request.POST.get('file_id', '').strip() or None
    task = None

    try:
        run = start_prediction(
            user=request.user,
            model_names=model_names,
            antibiotics=antibiotics,
            file_id=file_id,
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