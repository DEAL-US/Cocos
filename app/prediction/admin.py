from django.contrib import admin

from core.admin import TaskAdmin
from .models import PredictionRun, PredictionTask

@admin.register(PredictionTask)
class PredictionTaskAdmin(TaskAdmin):
    list_display = TaskAdmin.list_display + ('run',)
    raw_id_fields = TaskAdmin.raw_id_fields + ('run',)


class PredictionTaskInline(admin.TabularInline):
    model = PredictionTask
    fk_name = 'run'
    fields = ('step', 'status', 'parameters', 'results')
    readonly_fields = fields
    extra = 0
    can_delete = False
    show_change_link = True


@admin.register(PredictionRun)
class PredictionRunAdmin(admin.ModelAdmin):
    list_display = ('id', 'status', 'process', 'selected_models', 'selected_antibiotics', 'created_at', 'updated_at')
    list_filter = ('status',)
    search_fields = ('process__name',)
    raw_id_fields = ('process', 'output_csv')
    inlines = (PredictionTaskInline,)
