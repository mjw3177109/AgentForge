from django.urls import path

from .views import dashboard

app_name = "agentforge_django"
urlpatterns = [path("", dashboard, name="dashboard")]
