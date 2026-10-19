from django.contrib import admin

from .models import AgentJob, AuditEvent, JobLease, ManagedProject, MutationApproval


@admin.register(ManagedProject)
class ManagedProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "enabled", "autonomous_enabled", "run_business_tests",
                    "root_path")
    list_filter = ("enabled", "autonomous_enabled")
    search_fields = ("name", "root_path")


@admin.register(AgentJob)
class AgentJobAdmin(admin.ModelAdmin):
    list_display = ("id", "project", "mode", "status", "created_at", "finished_at")
    list_filter = ("mode", "status", "project")
    readonly_fields = ("status", "result", "started_at", "finished_at", "created_at")
    actions = ("reset_pending",)

    @admin.action(description="仅将未运行的 PENDING 任务留在队列（不执行）")
    def reset_pending(self, request, queryset):
        self.message_user(request, "请使用 run_agentforge_job 管理命令运行队列；网页不执行任意代码。")

    def save_model(self, request, obj, form, change):
        if not change and not obj.requested_by_id:
            obj.requested_by = request.user
        super().save_model(request, obj, form, change)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MutationApproval)
class MutationApprovalAdmin(admin.ModelAdmin):
    list_display = ("job", "approved_by", "base_commit", "approved_at")
    readonly_fields = ("approved_at", "request_sha256", "configuration_sha256")
    exclude = ("approved_by",)

    def save_model(self, request, obj, form, change):
        if change:
            raise ValueError("Mutation approval is immutable")
        obj.approved_by = request.user
        super().save_model(request, obj, form, change)

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("job", "sequence", "phase", "decision", "created_at")
    list_filter = ("phase", "decision")
    readonly_fields = ("job", "sequence", "phase", "decision", "detail",
                       "previous_hash", "event_hash", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

@admin.register(JobLease)
class JobLeaseAdmin(admin.ModelAdmin):
    list_display = ("project", "job", "acquired_at", "owner_token")
    readonly_fields = ("project", "job", "acquired_at", "owner_token")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
