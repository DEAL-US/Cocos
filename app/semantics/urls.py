from django.urls import path

from . import views

app_name = 'semantics'

urlpatterns = [
    path('processes/<int:process_id>/rdf/', views.process_rdf_view, name='process_rdf'),
    path('processes/<int:process_id>/flow/', views.process_flow_view, name='process_flow'),
    path('processes/<int:process_id>/predictions/<int:run_id>/ro-crate/', views.prediction_crate_view,
         name='prediction_crate'),
    path('sparql', views.sparql_view, name='sparql'),
    path('registry/', views.registry_view, name='registry'),
    path('step/<str:key>', views.step_view, name='step'),
    path('model/<str:name>', views.model_view, name='model'),
    path('amrf/', views.vocabulary_view, name='vocabulary'),
    path('amrf/shapes', views.shapes_view, name='shapes'),
    path('amrf/<str:term>', views.vocabulary_term_view, name='vocabulary_term'),
]
