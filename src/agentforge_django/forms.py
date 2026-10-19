"""Validation for operator-intended actions. No actions execute inside HTTP requests."""
from django import forms
from django.conf import settings

from .guard import BoundaryDenied, checked_root
from .models import AgentJob, ManagedProject


class NewJobForm(forms.Form):
    project = forms.ModelChoiceField(
        queryset=ManagedProject.objects.none(), label="目标项目",
        empty_label="请选择已启用的项目",
    )
    mode = forms.ChoiceField(choices=AgentJob.Mode.choices, label="运行模式")
    request = forms.CharField(
        max_length=4000, required=False, label="目标或巡检说明",
        widget=forms.Textarea(attrs={"rows": 4, "placeholder": "描述目标、范围和可验收标准"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["project"].queryset = ManagedProject.objects.filter(
            enabled=True
        ).order_by("name")

    def clean(self):
        result = super().clean()
        project = result.get("project")
        mode = result.get("mode")
        if project:
            try:
                checked_root(project.root_path)
            except (BoundaryDenied, OSError, ValueError):
                self.add_error("project", "目标目录不在管理员授权的项目范围内")
        if mode == AgentJob.Mode.AUTONOMOUS:
            if not result.get("request", "").strip():
                self.add_error("request", "自治任务必须描述可验收的目标")
            if project and not project.autonomous_enabled:
                self.add_error("mode", "项目未开启自治开关")
            if not getattr(settings, "AGENTFORGE_ALLOW_AUTONOMOUS", False):
                self.add_error("mode", "全局自治开关仍关闭")
        if mode == AgentJob.Mode.VERIFY and project and not project.run_business_tests:
            self.add_error("mode", "该项目已关闭业务测试，无法提交 VERIFY")
        return result


class ApprovalForm(forms.Form):
    reason = forms.CharField(
        label="人工审批理由及验证要求", min_length=12, max_length=1000,
        widget=forms.Textarea(attrs={
            "rows": 4, "placeholder": "注明本次允许修改的范围、验收证据和审批依据",
        }),
    )
    acknowledge = forms.BooleanField(
        label="我确认只授权生成候选补丁，不授予合并或生产发布权限",
    )
