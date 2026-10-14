from django.urls import path
from . import views

app_name = 'prediction'

urlpatterns = [
    path('prediction/', views.prediction_ui, name='prediction'),
    path('prediction/matrix/', views.make_prediction_view, name='prediction_matrix'),
    path('prediction/<int:prediction_run_id>/csv/', views.download_prediction_csv, name='download_csv'),
]
