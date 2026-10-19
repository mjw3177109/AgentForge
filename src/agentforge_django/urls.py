from django.urls import path

from .views import (
    approve_job, dashboard, download_candidate_patch, download_evidence,
    job_detail, new_job, project_detail,
)

app_name = "agentforge_django"
urlpatterns = [
    path("", dashboard, name="dashboard"),
    path("projects/<int:project_id>/", project_detail, name="project_detail"),
    path("jobs/new/", new_job, name="new_job"),
    path("jobs/<uuid:job_id>/", job_detail, name="job_detail"),
    path("jobs/<uuid:job_id>/approve/", approve_job, name="approve_job"),
    path("jobs/<uuid:job_id>/evidence.json", download_evidence, name="download_evidence"),
    path("jobs/<uuid:job_id>/candidate.patch", download_candidate_patch,
         name="download_candidate_patch"),
]
