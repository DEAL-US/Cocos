from django.contrib import admin

from core.models import Gene, FileGene, File, ProcessGroup, TaskInput, TaskOutput


@admin.register(Gene)
class GeneAdmin(admin.ModelAdmin):
    list_display = ('id', 'identifiers')
    search_fields = ('identifiers',)

@admin.register(FileGene)
class FileGeneAdmin(admin.ModelAdmin):
    list_display = ('id', 'file', 'gene', 'expert')
    search_fields = ('expert', 'gene__identifiers', 'file__file')

@admin.register(File)
class FileAdmin(admin.ModelAdmin):
    list_display = ('id', 'created_at', 'file', 'file_type', 'user')
    search_fields = ('file',)

@admin.register(ProcessGroup)
class ProcessGroupAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'user', 'organism')
    list_filter = ('organism',)
    search_fields = ('name', 'user__username')


class TaskInputInline(admin.TabularInline):
    model = TaskInput
    extra = 0
    raw_id_fields = ('file',)


class TaskOutputInline(admin.TabularInline):
    model = TaskOutput
    extra = 0
    raw_id_fields = ('file',)


class TaskAdmin(admin.ModelAdmin):
    """Base admin for the concrete task models: what step ran, in which process, and on which files."""
    list_display = ('id', 'step', 'status', 'process', 'plan_node', 'created_at', 'started_at', 'finished_at')
    list_filter = ('status', 'step')
    search_fields = ('step', 'plan_node', 'external_job_id', 'process__name')
    raw_id_fields = ('process',)
    inlines = (TaskInputInline, TaskOutputInline)
