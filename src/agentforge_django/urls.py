from django.urls import path

from .views import dashboard, job_detail

app_name = "agentforge_django"
urlpatterns = [
    path("", dashboard, name="dashboard"),
    path("jobs/<uuid:job_id>/", job_detail, name="job_detail"),
]
