from django.urls import path

from . import views

app_name = 'semantics'

urlpatterns = [
    path('processes/<int:process_id>/rdf/', views.process_rdf_view, name='process_rdf'),
]
