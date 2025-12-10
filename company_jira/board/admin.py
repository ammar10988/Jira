from django.contrib import admin
from .models import Profile, Project, Issue, Comment, Attachment, ProjectAttachment  # adjust to your existing imports
admin.site.register(Project)

@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "department")
    list_filter = ("role", "department")
    search_fields = ("user__username", "user__email")
