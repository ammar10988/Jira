# board/notifications.py
from django.contrib.auth import get_user_model

from .models import Notification, Profile, Project, Issue

User = get_user_model()


def _boss_ids():
    """All users with role BOSS."""
    return Profile.objects.filter(
        role=Profile.ROLE_BOSS
    ).values_list("user_id", flat=True)


def _lead_ids_for_department(department):
    """
    All leads for a given department code.
    (Currently not used in issue notifications, but kept for future use.)
    """
    if not department:
        return []
    return Profile.objects.filter(
        role=Profile.ROLE_LEAD,
        department=department,
    ).values_list("user_id", flat=True)


# ---------------------------------------------------------------------
# 1) Project created (we already use this in ProjectCreateView)
# ---------------------------------------------------------------------
def create_project_created_notifications(project: Project):
    """
    Notify:
      - all project members
      - all BOSS users
    when a project is created.
    """
    member_ids = project.members.values_list("id", flat=True)
    boss_ids = _boss_ids()

    recipient_ids = set(member_ids) | set(boss_ids)

    # don’t notify the creator about their own action
    if project.owner_id in recipient_ids:
        recipient_ids.remove(project.owner_id)

    verb = f"{project.owner.username} created project: {project.name}"

    for uid in recipient_ids:
        Notification.objects.create(
            user_id=uid,
            project=project,
            verb=verb,
        )


# ---------------------------------------------------------------------
# 2) Issue / Status activity on a project
# ---------------------------------------------------------------------
def create_issue_activity_notifications(issue: Issue, actor: User, verb: str):
    """
    Notify on issue/status activity:

      Recipients:
        - all BOSS users (all departments)
        - the project owner, if they are a Team Lead
        - any Team Lead who is a member of this project
      Excludes:
        - the actor (person who did the update)
        - normal employees
        - team leads from other projects/departments who are not on this project

    'verb' is the human text like:
      "ammar updated status" / "lakshita reported an issue"
    """
    project = issue.project
    if project is None:
        return

    # 1) All bosses
    boss_ids = set(_boss_ids())

    # 2) Project owner, if they are a Team Lead
    lead_ids = set()
    owner = project.owner
    if (
        owner is not None
        and hasattr(owner, "profile")
        and owner.profile.role == Profile.ROLE_LEAD
    ):
        lead_ids.add(owner.id)

    # 3) Any Team Lead who is a member of this project
    lead_member_ids = project.members.filter(
        profile__role=Profile.ROLE_LEAD
    ).values_list("id", flat=True)
    lead_ids.update(lead_member_ids)

    # Combine all recipients
    recipient_ids = boss_ids | lead_ids

    # 4) Don't notify the actor themselves
    if actor and actor.id in recipient_ids:
        recipient_ids.remove(actor.id)

    if not recipient_ids:
        return

    # Final message text
    full_verb = f"{verb} – {project.name}"

    for uid in recipient_ids:
        Notification.objects.create(
            user_id=uid,
            project=project,
            verb=full_verb,
        )
