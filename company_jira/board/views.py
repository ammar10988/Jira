from django.db.models import Q
from django.contrib.auth import logout


from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic import TemplateView, DetailView, CreateView, UpdateView, ListView

from .models import Project, Issue, Comment, Attachment, ProjectAttachment, Profile
from .forms import ProjectForm, IssueForm, CommentForm, AttachmentForm, ProjectAttachmentForm, ProjectMembersForm

from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.http import HttpResponseRedirect, JsonResponse
from django.contrib import messages
from django.urls import reverse

from django.contrib.auth.models import User
from django.views.generic import ListView
from django.db import transaction

from django.http import Http404

from django.utils import timezone
from django.http import HttpResponseForbidden

from django.contrib.auth import get_user_model, login
from django.core.mail import send_mail
from .forms import OTPLoginRequestForm, OTPVerifyForm
from .models import EmailOTP

from django.contrib.auth.decorators import login_required, user_passes_test
from django.views import View
from .forms import InviteUserForm

from .models import Notification
from .models import Project, ProjectAttachment, Notification
from .notifications import (
    create_project_created_notifications,
    create_issue_activity_notifications,
)
#------------DashboardView---------------------------------------------------------#

class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "board/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        profile = getattr(user, "profile", None)

        # ---------- Which projects does this user see? ----------
        if profile and profile.role == Profile.ROLE_BOSS:
            # Boss sees all projects, all departments
            projects = Project.objects.all()
        else:
            # Team Lead / Employee: projects where they are owner OR member
            # (no department restriction so cross-department work is visible)
            projects = Project.objects.filter(
                Q(owner=user) | Q(members=user)
            ).distinct()

        ctx["projects"] = projects

        # ---------- Limit issues to those projects ----------
        issues_qs = Issue.objects.filter(project__in=projects)

        # Overview counts (only from visible projects)
        ctx["issue_counts"] = {
            "todo": issues_qs.filter(status="TODO").count(),
            "in_progress": issues_qs.filter(status="IN_PROGRESS").count(),
            "done": issues_qs.filter(status="DONE").count(),
        }

        # Priority breakdown (same filter)
        ctx["priority_counts"] = {
            "low": issues_qs.filter(priority="LOW").count(),
            "medium": issues_qs.filter(priority="MEDIUM").count(),
            "high": issues_qs.filter(priority="HIGH").count(),
            "critical": issues_qs.filter(priority="CRITICAL").count(),
        }

        # Recently updated (only from these projects)
        ctx["recent_issues"] = (
            issues_qs.select_related("project", "assignee")
            .order_by("-updated_at")[:5]
        )

        # Keep your existing context
        ctx["profile"] = profile
        ctx["department_choices"] = Profile.DEPARTMENT_CHOICES

        return ctx

#------------------------------------------END-----------------------------------------------------------------------------------------#

class ProjectBoardView(LoginRequiredMixin, DetailView):
    model = Project
    template_name = "board/project_board.html"
    context_object_name = "project"

    def get_queryset(self):
        user = self.request.user
        # If the user is a boss, they can see ALL projects
        profile = getattr(user, "profile", None)
        if profile and profile.role == "BOSS":
            return Project.objects.all()

        # Everyone else (lead / employee) only sees projects they own or are a member of
        return Project.objects.filter(
            Q(owner=user) | Q(members=user)
        ).distinct()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        project = self.object
        # only show issues that are intended for the board
        ctx["todo"] = project.issues.filter(status="TODO", show_on_board=True)
        ctx["in_progress"] = project.issues.filter(status="IN_PROGRESS", show_on_board=True)
        ctx["done"] = project.issues.filter(status="DONE", show_on_board=True)
        ctx["issue_form"] = IssueForm()
        ctx["project_attachment_form"] = ProjectAttachmentForm()
        return ctx

    def post(self, request, *args, **kwargs):
        import logging
        logger = logging.getLogger(__name__)

        self.object = self.get_object()

        # 🚫 Block Boss from creating status or issues
        if getattr(request.user.profile, "role", None) == "BOSS":
            messages.error(request, "Boss cannot create status or issues.")
            return redirect("project_board", pk=self.object.pk)

        project = self.object
        action = request.POST.get("action")


        form = IssueForm(request.POST, request.FILES)

        def render_with_errors(bound_form):
            logger.warning(
                "ProjectBoard form invalid for user %s on project %s: %s",
                request.user.username, project.pk, bound_form.errors.as_json()
            )
            for field, errs in bound_form.errors.items():
                for e in errs:
                    messages.error(request, f"{field}: {e}")
            ctx = self.get_context_data()
            ctx["issue_form"] = bound_form
            return render(request, self.template_name, ctx)

        # -------------------------------------------------
        # QUICK STATUS UPDATE
        # -------------------------------------------------
        if action == "status":
            if form.is_valid():
                issue = form.save(commit=False)
                issue.project = project
                issue.title = request.POST.get("title", "Status update")
                issue.assignee = request.user
                issue.show_on_board = True
                issue.save()
                form.save_m2m()

                files = request.FILES.getlist("attachments")
                for f in files:
                    Attachment.objects.create(issue=issue, file=f, uploaded_by=request.user)

                # 🔔 notify department lead + all bosses
                verb = f"{request.user.username} updated project status"
                create_issue_activity_notifications(issue, actor=request.user, verb=verb)

                messages.success(request, "Status saved and visible in My Tasks.")
                return redirect("project_board", pk=project.pk)
            else:
                return render_with_errors(form)

        # -------------------------------------------------
        # ISSUE / BLOCKER
        # -------------------------------------------------
        elif action in ("status_issue", "issue"):
            form = IssueForm(request.POST, request.FILES)

            if form.is_valid():
                cleaned = form.cleaned_data
                existing = Issue.objects.filter(
                    project=project,
                    show_on_board=True
                ).order_by("-created_at").first()

                if existing:
                    issue = existing
                    if cleaned.get("title"):
                        issue.title = cleaned["title"]
                    if "description" in cleaned:
                        issue.description = cleaned.get("description", issue.description)
                    if "members" in cleaned:
                        issue.members.set(cleaned["members"])
                    issue.save()
                else:
                    issue = form.save(commit=False)
                    issue.project = project
                    issue.assignee = request.user
                    issue.show_on_board = True
                    issue.save()
                    if hasattr(form, "save_m2m"):
                        form.save_m2m()

                files = request.FILES.getlist("attachments")
                for f in files:
                    Attachment.objects.create(issue=issue, file=f, uploaded_by=request.user)

                # 🔔 notify department lead + all bosses
                verb = f"{request.user.username} reported an issue"
                create_issue_activity_notifications(issue, actor=request.user, verb=verb)

                messages.success(
                    request,
                    "Issue saved — updated the project view without changing its status."
                )
                return redirect("project_board", pk=project.pk)

            logger.warning(
                "ProjectBoard form invalid for user %s on project %s: %s",
                request.user.username, project.pk, form.errors.as_json()
            )

            for field, errs in form.errors.items():
                for e in errs:
                    messages.error(request, f"{field}: {e}")

            ctx = self.get_context_data()
            ctx["issue_form"] = form
            return render(request, self.template_name, ctx)




    
#--------------------------ProjectCreateView-------------------------------------#

def create_project_created_notifications(project):
    """
    Create a notification for every member of a newly-created project.
    """
    # Message shown in notification
    message = f"{project.owner.username} created project: {project.name}"

    # Notify all project members (employees the lead/boss selected)
    recipients = project.members.all()

    for user in recipients:
        Notification.objects.create(
            user=user,
            verb=message,
            project=project,
        )


class ProjectCreateView(LoginRequiredMixin, CreateView):
    model = Project
    form_class = ProjectForm
    template_name = "board/project_form.html"

    def form_valid(self, form):
        project = form.save(commit=False)
        project.owner = self.request.user

        # Set department from creator’s profile
        profile = getattr(self.request.user, "profile", None)
        if profile and profile.department:
            project.department = profile.department

        # Save reference URL from the form (optional)
        project.reference_url = form.cleaned_data.get("reference_url")

        project.save()
        form.save_m2m()  # members, etc.

        # attachments
        files = self.request.FILES.getlist("attachments")
        for f in files:
            ProjectAttachment.objects.create(
                project=project,
                file=f,
                uploaded_by=self.request.user,
            )

        # 🔔 notify project members + bosses
        create_project_created_notifications(project)

        messages.success(self.request, "Project created.")
        return redirect("project_board", pk=project.pk)





#--------------------END---------------------------------------------------------------------------#

class IssueCreateView(LoginRequiredMixin, CreateView):
    model = Issue
    form_class = IssueForm

    def form_valid(self, form):
        project_id = self.kwargs["project_id"]
        project = get_object_or_404(Project, pk=project_id)
        form.instance.project = project
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy("project_board", kwargs={"pk": self.kwargs["project_id"]})


class IssueUpdateView(LoginRequiredMixin, UpdateView):
    model = Issue
    form_class = IssueForm
    template_name = "board/issue_form.html"

    def get_success_url(self):
        return reverse_lazy("project_board", kwargs={"pk": self.object.project.pk})
    
class IssueDetailView(LoginRequiredMixin, DetailView):
    model = Issue
    template_name = "board/issue_detail.html"
    context_object_name = "issue"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["comment_form"] = CommentForm()
        ctx["attachment_form"] = AttachmentForm()
        return ctx


class TeamListView(LoginRequiredMixin, ListView):
    model = User
    template_name = "board/team_list.html"
    context_object_name = "members"

    def get_queryset(self):
        # Show only active users, ordered by username
        return User.objects.filter(is_active=True).order_by("username")

#----------------------------Department-List----------------------------------------------------------------#
class DepartmentProjectsView(LoginRequiredMixin, TemplateView):
    template_name = "board/department_projects.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        dept_code = self.kwargs["dept_code"]  # e.g. "DEV"
        # find the label from choices, e.g. "Developer"
        dept_label = dict(Profile.DEPARTMENT_CHOICES).get(dept_code, dept_code)

        # All users in this department
        members = User.objects.filter(profile__department=dept_code).select_related(
            "profile"
        )

        # All projects that belong to this department
        # (either the owner or any member is in this department)
        projects = (
            Project.objects.filter(
                Q(owner__profile__department=dept_code)
                | Q(members__profile__department=dept_code)
            )
            .distinct()
            .order_by("name")
        )

        # All issues in those projects
        issues = (
            Issue.objects.filter(project__in=projects)
            .select_related("project", "assignee")
            .order_by("-updated_at")
        )

        # Status counts for the summary
        ctx["dept_code"] = dept_code
        ctx["dept_label"] = dept_label

        ctx["todo_count"] = issues.filter(status="TODO").count()
        ctx["in_progress_count"] = issues.filter(status="IN_PROGRESS").count()
        ctx["done_count"] = issues.filter(status="DONE").count()

        ctx["projects"] = projects
        ctx["members"] = members
        ctx["recent_issues"] = issues[:5]

        return ctx

#--------------------------------------------------------------------------------------------#
@login_required
def logout_view(request):
    logout(request)
    return redirect("login")

@require_POST
def update_issue_status(request, pk):
    issue = get_object_or_404(Issue, pk=pk, assignee=request.user)
    new_status = request.POST.get("status")

    valid_statuses = {value for value, _ in Issue.STATUS_CHOICES}
    if new_status in valid_statuses:
        issue.status = new_status
        issue.save()

    next_url = request.POST.get("next") or reverse("my_tasks")
    return HttpResponseRedirect(next_url)



class MyTasksView(LoginRequiredMixin, ListView):
    model = Issue
    template_name = "board/my_tasks.html"
    context_object_name = "issues"

    def get_queryset(self):
        user = self.request.user

        # start with issues assigned to the user OR where they are in members
        qs = Issue.objects.filter(
            Q(assignee=user) | Q(members=user)
        ).distinct()

        status = self.request.GET.get("status")
        priority = self.request.GET.get("priority")
        order = self.request.GET.get("order")

        if status and status != "all":
            qs = qs.filter(status=status)
        if priority and priority != "all":
            qs = qs.filter(priority=priority)

        if order == "due_asc":
            qs = qs.order_by("due_date", "priority")
        elif order == "due_desc":
            qs = qs.order_by("-due_date", "-priority")
        elif order == "prio_desc":
            qs = qs.order_by("-priority", "status")
        elif order == "updated_desc":
            qs = qs.order_by("-updated_at")
        else:
            qs = qs.order_by("status", "-updated_at")

        # pull related objects efficiently
        return qs.select_related("project", "assignee").prefetch_related("attachments")


    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["status_choices"] = Issue.STATUS_CHOICES
        ctx["priority_choices"] = Issue.PRIORITY_CHOICES
        ctx["current_status"] = self.request.GET.get("status", "all")
        ctx["current_priority"] = self.request.GET.get("priority", "all")
        ctx["current_order"] = self.request.GET.get("order", "default")

        # summary counts
        all_my = Issue.objects.filter(assignee=self.request.user)
        from django.utils import timezone
        today = timezone.localdate()

        summary = {
            "todo": all_my.filter(status="TODO").count(),
            "in_progress": all_my.filter(status="IN_PROGRESS").count(),
            "done": all_my.filter(status="DONE").count(),
            "overdue": all_my.filter(due_date__lt=today)
                             .exclude(status="DONE")
                             .count(),
        }
        ctx["summary"] = summary

        # --------------------------
        # NEW: choose which issue the "View Issue" link should open
        # --------------------------
        # ctx['issues'] is the ListView object_list (the queryset we returned)
        issues = list(ctx.get("issues", []))

        # collect project ids for the issues currently in the table
        project_ids = {i.project_id for i in issues}

        # For each project, find the latest non-board issue (show_on_board=False).
        # Portable approach: one query per project (fine for small number of projects).
        latest_non_board_by_project = {}
        if project_ids:
            for pid in project_ids:
                latest = (
                    Issue.objects
                         .filter(project_id=pid, show_on_board=False)
                         .order_by("-created_at")
                         .first()
                )
                if latest:
                    latest_non_board_by_project[pid] = latest

        # attach helper attribute view_issue_pk to each issue in the table
        # so the template can link to the "detailed" issue while leaving the
        # board-row title/status untouched.
        for issue in issues:
            latest = latest_non_board_by_project.get(issue.project_id)
            if latest:
                issue.view_issue_pk = latest.pk
            else:
                issue.view_issue_pk = issue.pk

        # put the (possibly annotated) list back into context
        ctx["issues"] = issues

        return ctx


@login_required
@require_POST
def add_comment(request, pk):
    issue = get_object_or_404(Issue, pk=pk)
    form = CommentForm(request.POST)
    if form.is_valid():
        comment = form.save(commit=False)
        comment.issue = issue
        comment.author = request.user
        comment.save()
        messages.success(request, "Comment added.")
    return HttpResponseRedirect(reverse("issue_detail", args=[issue.pk]))


@login_required
@require_POST
def add_attachment(request, pk):
    issue = get_object_or_404(Issue, pk=pk)
    form = AttachmentForm(request.POST, request.FILES)
    if form.is_valid():
        att = form.save(commit=False)
        att.issue = issue
        att.uploaded_by = request.user
        att.save()
        messages.success(request, "File uploaded.")
    else:
        messages.error(request, "Error uploading file.")
    return HttpResponseRedirect(reverse("issue_detail", args=[issue.pk]))


@login_required
@require_POST
def delete_comment(request, pk):
    comment = get_object_or_404(Comment, pk=pk)
    issue = comment.issue

    if request.user == comment.author or request.user.is_staff:
        comment.delete()
        messages.success(request, "Comment deleted.")
    else:
        messages.error(request, "You do not have permission to delete this comment.")

    return HttpResponseRedirect(reverse("issue_detail", args=[issue.pk]))




@login_required
@require_POST
def delete_attachment(request, pk):
    attachment = get_object_or_404(Attachment, pk=pk)
    issue = attachment.issue

    if request.user == attachment.uploaded_by or request.user.is_staff:
        attachment.delete()
        messages.success(request, "Attachment deleted.")
    else:
        messages.error(request, "You do not have permission to delete this attachment.")

    return HttpResponseRedirect(reverse("issue_detail", args=[issue.pk]))


class ProfileView(LoginRequiredMixin, TemplateView):
    template_name = "board/profile.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        from .models import Issue
        ctx["user_issues"] = Issue.objects.filter(assignee=user).order_by("-updated_at")[:10]
        return ctx
    

from django.db.models import Q

@login_required
@require_POST
def add_project_attachment(request, pk):
    project = get_object_or_404(
        Project,
        Q(owner=request.user) | Q(members=request.user),
        pk=pk,
    )

    form = ProjectAttachmentForm(request.POST, request.FILES)
    if form.is_valid():
        att = form.save(commit=False)
        att.project = project
        att.uploaded_by = request.user
        att.save()
        messages.success(request, "Project file uploaded.")
    else:
        messages.error(request, "Error uploading file.")
    return redirect("project_board", pk=project.pk)

@login_required
def issue_create(request, project_id):
    # make sure user is allowed to add issues to this project
    project = get_object_or_404(
        Project.objects.filter(
            Q(owner=request.user) | Q(members=request.user)
        ),
        pk=project_id,
    )

    if request.method == "POST":
        form = IssueForm(request.POST, request.FILES)
        if form.is_valid():
            issue = form.save(commit=False)
            issue.project = project
            issue.save()
            form.save_m2m()  # saves members many-to-many

            # Create Attachment rows for uploaded files
            files = request.FILES.getlist("attachments")
            for f in files:
                Attachment.objects.create(
                    issue=issue,
                    file=f,
                    uploaded_by=request.user,
                )

            messages.success(request, "Issue created.")
            return redirect("project_board", pk=project.pk)
    else:
        form = IssueForm()

    return render(
        request,
        "board/issue_form.html",   # or project_board.html if you render inline
        {"form": form, "project": project},
    )


#---------------------TEAM-LEAD---------------------------------------------------------#

class TeamLeadDashboardView(LoginRequiredMixin, TemplateView):
    template_name = "board/teamlead_dashboard.html"

    def get_projects_for_lead(self, user):
        """
        Return projects the lead should see.
        Currently returns projects where the user is owner OR member.
        """
        return Project.objects.filter(Q(owner=user) | Q(members=user)).distinct()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user

        projects = self.get_projects_for_lead(user)

        # optional: recent timeframe (remove filter to show all)
        recent_cutoff = timezone.now() - timezone.timedelta(days=60)

        # Fetch board-visible issues in those projects, newest first.
        # These are the items a Lead will want to review.
        # We pull related() to include assignee and project for the template.
        status_updates = (
            Issue.objects
                 .filter(project__in=projects, show_on_board=True)
                 .filter(created_at__gte=recent_cutoff)
                 .select_related("project", "assignee")
                 .order_by("-created_at")
        )

        # If you prefer to only show items created via the "status" action
        # (where title == "Status update"), uncomment the next line:
        # status_updates = status_updates.filter(title__iexact="Status update")

        ctx["status_updates"] = status_updates
        ctx["projects"] = projects
        return ctx

#----------------------------Boss-team-view----------------------------------------#
class BossDashboardView(LoginRequiredMixin, TemplateView):
    template_name = "board/boss_dashboard.html"

    def get_projects_for_boss(self, user):
        """
        Boss should see ALL projects (across all team leads / departments).

        If later you want to restrict by the boss's department,
        you can add a filter here.
        """
        projects = Project.objects.all()

        # If your Project has a department field and you want
        # the boss to only see one department, uncomment this:
        #
        # profile = getattr(user, "profile", None)
        # if profile and profile.department:
        #     projects = projects.filter(department=profile.department)

        return projects.distinct()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user

        # now this includes *all* projects the boss should see
        projects = self.get_projects_for_boss(user)

        # last 60 days of status updates on those projects
        recent_cutoff = timezone.now() - timezone.timedelta(days=60)
        status_updates = (
            Issue.objects
                 .filter(project__in=projects, show_on_board=True)
                 .filter(created_at__gte=recent_cutoff)
                 .select_related("project", "assignee")
                 .order_by("-created_at")
        )

        ctx["status_updates"] = status_updates
        ctx["projects"] = projects
        return ctx

    


#-----------------------------Delete Button------------------------------------#

@login_required
def project_delete(request, pk):
    """
    Allow only LEAD and BOSS to delete a project.
    (You can tighten this rule if you want to restrict to project.owner etc.)
    """
    project = get_object_or_404(Project, pk=pk)

    # Get role safely
    profile = getattr(request.user, "profile", None)
    role = getattr(profile, "role", "EMP")

    # Only Boss or Team Lead can delete
    if role not in ("BOSS", "LEAD"):
        return HttpResponseForbidden("You are not allowed to delete this project.")

    if request.method == "POST":
        name = project.name
        project.delete()
        messages.success(request, f'Project "{name}" was deleted.')
        return redirect("dashboard")

    # GET -> show a simple confirmation page
    return render(request, "board/project_confirm_delete.html", {"project": project})




#-------------------------------------------------OTP-LOGIN----------------------------------------------------------------------#

User = get_user_model()


def otp_login_request(request):
    """
    Step 1: User submits email. If it exists and is allowed,
    generate + email an OTP code.
    """
    if request.method == "POST":
        form = OTPLoginRequestForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data["email"].lower()

            # ✅ Restrict to your company domains
            allowed_domains = {"garagecollective.ag", "garagecollective.agency"}
            domain = email.split("@")[-1]
            if domain not in allowed_domains:
                messages.error(request, "Please use your company work email address.")
                return render(request, "registration/otp_login.html", {"form": form})

            # Must already exist in User table
            try:
                user = User.objects.get(email__iexact=email)
            except User.DoesNotExist:
                messages.error(request, "No account found with that email.")
                return render(request, "registration/otp_login.html", {"form": form})

            # Generate and store OTP
            code = EmailOTP.generate_code()
            EmailOTP.objects.create(user=user, email=email, code=code)

            # Send OTP by email
            send_mail(
                subject="Your login code",
                message=f"Your login code is: {code}\n\nIt expires in 10 minutes.",
                from_email=None,
                recipient_list=[email],
                fail_silently=False,
            )

            # Optionally remember the email in session for convenience
            request.session["otp_email"] = email

            messages.success(request, "OTP sent to your email. Please enter it below.")
            return redirect("otp_verify")
    else:
        form = OTPLoginRequestForm()

    return render(request, "registration/otp_login.html", {"form": form})


def otp_login_verify(request):
    """
    Step 2: User enters email + OTP. If valid, log them in.
    """
    initial = {}
    # pre-fill email from session if we stored it
    if "otp_email" in request.session:
        initial["email"] = request.session["otp_email"]

    if request.method == "POST":
        form = OTPVerifyForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data["email"].lower()
            code = form.cleaned_data["code"].strip()

            try:
                otp_obj = (
                    EmailOTP.objects
                    .filter(email__iexact=email, code=code, is_used=False)
                    .latest("created_at")
                )
            except EmailOTP.DoesNotExist:
                messages.error(request, "Invalid code or email.")
                return render(request, "registration/otp_verify.html", {"form": form})

            # Check expiry
            if otp_obj.is_expired:
                messages.error(request, "This code has expired. Please request a new one.")
                return redirect("otp_login")

            # Mark used
            otp_obj.is_used = True
            otp_obj.save(update_fields=["is_used"])

            # Log in the user associated with this OTP
            user = otp_obj.user
            login(request, user)

            # Clean up session
            request.session.pop("otp_email", None)

            messages.success(request, "Logged in successfully.")
            return redirect("dashboard")
    else:
        form = OTPVerifyForm(initial=initial)

    return render(request, "registration/otp_verify.html", {"form": form})



#----------------------------------------USER WITH EMAIL-----------------------------------------------------------#

User = get_user_model()


def _is_boss_or_lead(user):
    return (
        user.is_authenticated
        and getattr(user.profile, "role", None) in ("BOSS", "LEAD")
    )


@method_decorator([login_required, user_passes_test(_is_boss_or_lead)], name="dispatch")
class InviteUserView(View):
    template_name = "board/invite_user.html"

    def get(self, request):
        form = InviteUserForm()
        return render(request, self.template_name, {"form": form})

    def post(self, request):
        form = InviteUserForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form})

        email = form.cleaned_data["email"].lower()
        full_name = form.cleaned_data.get("full_name", "").strip()
        role = form.cleaned_data["role"]
        department = form.cleaned_data.get("department")  # NEW

        # username from email local-part, ensure unique
        base_username = email.split("@")[0]
        username = base_username
        i = 1
        while User.objects.filter(username=username).exists():
            username = f"{base_username}{i}"
            i += 1

        user, created = User.objects.get_or_create(
            email__iexact=email,
            defaults={"username": username},
        )
        if created:
            # they will log in via OTP only
            user.set_unusable_password()
            if full_name:
                user.first_name = full_name  # or split into first/last if you want
            user.email = email
            user.save()
        else:
            # update name/email if you changed them
            if full_name:
                user.first_name = full_name
            user.email = email
            user.save()

        # Ensure profile exists and set role + department
        profile, _ = Profile.objects.get_or_create(user=user)
        profile.role = role
        if department:
            profile.department = department
        profile.save()

        # Optional: send them a welcome email with instructions
        send_mail(
            subject="You’ve been added to G-Track dashboard",
            message=(
                "Hi,\n\n"
                "You’ve been added to the Garage Collective G-Track dashboard.\n"
                "To log in, go to the OTP login page, enter this email address "
                "and use the one-time code you receive.\n\n"
                "Login page: https://garagecollective.agency/G-track/login/otp/\n"
            ),
            from_email=None,
            recipient_list=[email],
            fail_silently=True,
        )

        messages.success(
            request,
            f"User {email} saved with role {role}"
            + (f" in department {department}." if department else ".")
            + " They can now log in using OTP.",
        )
        return redirect("invite_user")


#-------------------------------------------------Notification-------------------------------------------------------------------#

class NotificationListView(LoginRequiredMixin, ListView):
    model = Notification
    template_name = "board/notifications.html"
    context_object_name = "notifications"

    def get_queryset(self):
        return (
            Notification.objects
            .filter(user=self.request.user)
            .select_related("project")
        )

    def post(self, request, *args, **kwargs):
        # Mark all current user's notifications as read
        Notification.objects.filter(
            user=request.user,
            is_read=False
        ).update(is_read=True)

        messages.success(request, "All notifications marked as read.")
        return redirect("notifications")
    

#-------------------------Edit Members----------------------------------------------#

class ProjectMembersUpdateView(LoginRequiredMixin, UpdateView):
    model = Project
    form_class = ProjectMembersForm
    template_name = "board/project_members_form.html"

    def dispatch(self, request, *args, **kwargs):
        role = getattr(request.user.profile, "role", None)
        if role not in ("BOSS", "LEAD"):
            messages.error(request, "You are not allowed to edit project members.")
            return redirect("project_board", pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        messages.success(self.request, "Project members updated.")
        return reverse("project_board", kwargs={"pk": self.object.pk})
