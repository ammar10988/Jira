from django.db import models
from django.contrib.auth.models import User


from django.conf import settings
from django.utils import timezone
import uuid
import random
import string

#Profile 
#-----------------------------------------------------------------------------------------------------------------------------#

class Profile(models.Model):
    ROLE_BOSS = "BOSS"
    ROLE_LEAD = "LEAD"
    ROLE_EMPLOYEE = "EMP"
    ROLE_CHOICES = [
        (ROLE_BOSS, "Director"),
        (ROLE_LEAD, "Team Lead"),
        (ROLE_EMPLOYEE, "Member"),
    ]

    DEPT_DEV = "DEV"
    DEPT_GRAPHIC = "GRAPHIC"
    DEPT_SOCIAL = "SOCIAL"
    DEPT_AI = "AI"
    DEPT_ELEARNING = "ELEARNING"
    DEPT_LEAD = "LEAD"
    DEPT_SEO = "SEO"

    DEPARTMENT_CHOICES = [
        (DEPT_DEV, "Developer"),
        (DEPT_GRAPHIC, "Graphic"),
        (DEPT_SOCIAL, "Social Media"),
        (DEPT_AI, "AI Developer"),
        (DEPT_ELEARNING, "eLearning"),
        (DEPT_LEAD, "Lead"),
        (DEPT_SEO, "SEO"),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=ROLE_EMPLOYEE)
    department = models.CharField(
        max_length=20, choices=DEPARTMENT_CHOICES, blank=True, null=True
    )

    def __str__(self):
        return f"{self.user.username} ({self.get_role_display()})"


#-----------------------------------------------------------------------------------------------------------------------------#

class Project(models.Model):
    name = models.CharField(max_length=100)
    key = models.CharField(
        max_length=10,
        unique=True,                      # keep this if you want each key only once
        help_text="Short code, e.g. CRM",
    )
    description = models.TextField(blank=True)

    # who owns / created the project
    owner = models.ForeignKey(
        User,
        related_name="owned_projects",
        on_delete=models.CASCADE,
    )

    # dates + SOP
    issue_date = models.DateField(null=True, blank=True)
    deadline_date = models.DateField(null=True, blank=True)
    sop = models.TextField(
        blank=True,
        help_text="Step-by-step SOP for this project.",
    )

    # 🔹 optional reference URL (Figma, Docs, Drive, etc.)
    reference_url = models.URLField(
        blank=True,
        null=True,
        help_text="Optional: link to docs / design / folder for this project.",
    )

    # team members on this project
    members = models.ManyToManyField(
        User,
        related_name="projects",
        blank=True,
        help_text="Team members who can see this project.",
    )

    # 🔹 department this project belongs to
    department = models.CharField(
        max_length=50,
        choices=Profile.DEPARTMENT_CHOICES,
        blank=True,
        null=True,
        help_text="Department this project belongs to",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.key} - {self.name}"



class ProjectAttachment(models.Model):
    project = models.ForeignKey(Project, related_name="attachments", on_delete=models.CASCADE)
    file = models.FileField(upload_to="project_attachments/")
    uploaded_by = models.ForeignKey(User, on_delete=models.CASCADE)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def filename(self):
        return self.file.name.split("/")[-1]

    def __str__(self):
        return f"{self.filename()} for {self.project}"


class Issue(models.Model):
    STATUS_CHOICES = [
        ("TODO", "To Do"),
        ("IN_PROGRESS", "In Progress"),
        ("DONE", "Done"),
    ]

    PRIORITY_CHOICES = [
        ("LOW", "Low"),
        ("MEDIUM", "Medium"),
        ("HIGH", "High"),
        ("CRITICAL", "Critical"),
    ]

    project = models.ForeignKey(Project, related_name="issues", on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="TODO")
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default="MEDIUM")
    assignee = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    members = models.ManyToManyField(
        User,
        related_name="issue_memberships",
        blank=True,
    )
    due_date = models.DateField(null=True, blank=True)

    # NEW: hide certain issues from the project board but keep them accessible elsewhere
    show_on_board = models.BooleanField(
        default=True,
        help_text="If false the issue is hidden from the project's kanban columns but still visible in My Tasks and issue detail."
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.project.key}-{self.id}: {self.title}"

    def is_overdue(self):
        """
        Returns True if the issue has a due_date in the past and is not Done.
        """
        if not self.due_date:
            return False
        if self.status == "DONE":
            return False
        today = timezone.localdate()
        return self.due_date < today


class Comment(models.Model):
    issue = models.ForeignKey(Issue, related_name="comments", on_delete=models.CASCADE)
    author = models.ForeignKey(User, on_delete=models.CASCADE)
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"Comment by {self.author} on {self.issue}"


class Attachment(models.Model):
    issue = models.ForeignKey(Issue, related_name="attachments", on_delete=models.CASCADE)
    file = models.FileField(upload_to="attachments/")
    uploaded_by = models.ForeignKey(User, on_delete=models.CASCADE)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def filename(self):
        return self.file.name.split("/")[-1]

    def __str__(self):
        return f"Attachment {self.file} for {self.issue}"


#---------------------------------OTP Login---------------------------------#


class EmailOTP(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="email_otps",
    )
    email = models.EmailField()
    code = models.CharField(max_length=6)  # 6-digit
    created_at = models.DateTimeField(auto_now_add=True)
    is_used = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=["email", "code"]),
        ]

    def __str__(self):
        return f"OTP for {self.email} ({self.code})"

    @classmethod
    def generate_code(cls) -> str:
        # 6-digit numeric code
        return "".join(random.choices(string.digits, k=6))

    @property
    def is_expired(self) -> bool:
        # 10-minute expiry window (adjust if you like)
        return self.created_at < timezone.now() - timezone.timedelta(minutes=10)
    


#----------------------------Notification---------------------------------------------------------------------#

class Notification(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    verb = models.CharField(max_length=255)  # what happened
    project = models.ForeignKey(
        "Project",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="notifications",
    )
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} – {self.verb}"