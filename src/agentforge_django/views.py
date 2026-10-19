from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render

from .models import AgentJob, ManagedProject


@staff_member_required
def dashboard(request):
    return render(request, "agentforge_django/dashboard.html", {
        "projects": ManagedProject.objects.all().order_by("name")[:50],
        "jobs": AgentJob.objects.select_related("project").all()[:50],
    })
