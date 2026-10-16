from django.urls import path
from .views import pipeline, status

app_name = "conversion"

urlpatterns = [
    path("assembly/", pipeline.assembly_ui, name="assembly_ui"),
    path("assembly/run/", pipeline.start_assembly_task, name="assembly_run"),
    path("annotation/", pipeline.annotation_ui, name="annotation_ui"),
    path("annotation/from-fasta/", pipeline.start_annotation_task, name="start_annotation_task"),
    path("annotation/from-json/", pipeline.parse_feature_file, name="annotation_from_json"),
    path('processes/', status.process_list_view, name='process_list'),
    path('processes/<int:process_id>/', status.process_status_view, name='process_status'),
    path('processes/<int:process_id>/rename/', status.rename_process_view, name='rename_process'),
    path('processes/<int:process_id>/files/<int:file_id>/', status.download_process_file_view, name='process_file'),
    path('tasks/<int:task_id>/download-json/', status.download_json_view, name='download_json'),
    path('tasks/<int:task_id>/download-fasta/', status.download_fasta_view, name='download_fasta'),
    path('tasks/<int:task_id>/download-fastq/', status.download_fastq_view, name='download_fastq'),
]
