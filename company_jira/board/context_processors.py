from django.utils import timezone
from .models import Issue
from .models import Notification

def user_issue_counts(request):
    if not request.user.is_authenticated:
        return {}
    today = timezone.localdate()
    overdue = Issue.objects.filter(
        assignee=request.user,
        due_date__lt=today
    ).exclude(status="DONE").count()
    open_issues = Issue.objects.filter(
        assignee=request.user
    ).exclude(status="DONE").count()

    return {
        "nav_overdue_count": overdue,
        "nav_open_issue_count": open_issues,
    }

#-----------------Notification-------------------------------#

def notifications_context(request):
    """
    Adds unread_notifications_count to every template.
    """
    if request.user.is_authenticated:
        count = Notification.objects.filter(
            user=request.user,
            is_read=False
        ).count()
    else:
        count = 0

    return {"unread_notifications_count": count}