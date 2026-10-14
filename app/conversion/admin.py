from django.contrib import admin

from conversion.models import ConversionTask
from core.admin import TaskAdmin

@admin.register(ConversionTask)
class ConversionTaskAdmin(TaskAdmin):
    list_display = TaskAdmin.list_display + ('external_job_id',)
