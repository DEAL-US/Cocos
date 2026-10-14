from .models import PredictionRun
from conversion.models import ConversionTask
from core.models import File, TaskStatus
from core.orchestration import extend_plan
from conversion.services.presentation import format_process_label

from .registry import get_model_supported_antibiotics
from .steps import PREDICTION_STEP_PREFIX


def get_prediction_input_options(user):
    """Genes produced by the user's completed gene extractions."""
    extractions = ConversionTask.objects.filter(
        process__user=user,
        status=TaskStatus.COMPLETED,
        task_outputs__role='genes',
    ).select_related('process').order_by('-created_at')
    options = []

    for task in extractions:
        genes_file = task.output_file('genes')

        # Files whose features could not be parsed have no genes to predict from.
        if not genes_file.genes.exists():
            continue

        options.append({
            'id': str(genes_file.id),
            'label': format_process_label(task),
        })

    return options

def get_valid_prediction_antibiotics(model_names, antibiotics):
    return [antibiotic for antibiotic in antibiotics if 
            any(antibiotic in get_model_supported_antibiotics(model_name) for model_name in model_names)]

def _get_source_task_for_prediction(file):
    """The gene extraction that produced the genes of `file`."""
    return ConversionTask.objects.filter(task_outputs__file=file, task_outputs__role='genes').select_related('process').first()

def get_prediction_file(user, file_id):
    if not file_id:
        raise ValueError('Select a dataset.')
    
    try:
        file = File.objects.get(pk=int(file_id), user=user, file_type=File.FileType.JSON)
    except (ValueError, File.DoesNotExist):
        raise ValueError('Selected file not found.')

    if not file.genes.exists():
        raise ValueError('Selected file has no annotated genes to predict from.')
    return file

def start_prediction(user, model_names, antibiotics, file_id):
    if not model_names:
        raise ValueError('Select at least one model.')

    if not antibiotics:
        raise ValueError('Select at least one antibiotic.')

    file = get_prediction_file(user, file_id)

    valid_antibiotics = get_valid_prediction_antibiotics(model_names, antibiotics)

    if not valid_antibiotics:
        raise ValueError('No valid antibiotic/model combinations found.')
    
    source_task = _get_source_task_for_prediction(file)
    process = source_task.process

    run = PredictionRun.objects.create(
        process=process,
        selected_models=model_names,
        selected_antibiotics=valid_antibiotics,
    )

    # One node per model, with the selected antibiotics it supports. Models that support none of
    # them get no task, so their column shows no result.
    nodes = []
    for model_name in model_names:
        model_antibiotics = [antibiotic for antibiotic in valid_antibiotics
                             if antibiotic in get_model_supported_antibiotics(model_name)]
        if model_antibiotics:
            nodes.append({
                'id': f'run{run.pk}_{model_name}',
                'step': f'{PREDICTION_STEP_PREFIX}{model_name}',
                'after': [source_task.plan_node],
                'run': run.pk,
                'parameters': {'antibiotics': model_antibiotics},
            })

    extend_plan(process, nodes)

    run.refresh_from_db()
    return run