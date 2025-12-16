from django import forms
from django.contrib.auth.models import User
from .models import Project, Issue, Comment, Attachment, ProjectAttachment
from django.contrib.auth import get_user_model
from .models import Profile

class ProjectForm(forms.ModelForm):
    members = forms.ModelMultipleChoiceField(
        queryset=User.objects.filter(is_active=True),
        required=False,
        widget=forms.SelectMultiple(attrs={"size": 6}),
        help_text="Select team members for this project.",
    )

    class Meta:
        model = Project
        fields = ["name", "key", "description", "issue_date", "deadline_date", "sop", "members", "reference_url"]
        widgets = {
            "issue_date": forms.DateInput(attrs={"type": "date"}),
            "deadline_date": forms.DateInput(attrs={"type": "date"}),
            "sop": forms.Textarea(attrs={"rows": 4}),
            "description": forms.Textarea(attrs={"rows": 4}),
            "reference_url": forms.URLInput(attrs={
                "class": "form-control",
                "placeholder": "https://example.com/specifications"
            }),
        }


class ProjectAttachmentForm(forms.ModelForm):
    class Meta:
        model = ProjectAttachment
        fields = ["file"]



class IssueForm(forms.ModelForm):
    # NOTE: attachments removed from the form. We handle files directly in the view via request.FILES.getlist("attachments")
    class Meta:
        model = Issue
        fields = [
            "title",
            "description",
            "status",
            "priority",
            "assignee",
            "members",
            "due_date",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "members": forms.SelectMultiple(attrs={"size": 4}),
            # IMPORTANT: browser will send ISO date (YYYY-MM-DD)
            "due_date": forms.DateInput(attrs={"type": "date"}),
        }





class CommentForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ["body"]
        widgets = {
            "body": forms.Textarea(attrs={"rows": 3, "placeholder": "Add a comment…"}),
        }


class AttachmentForm(forms.ModelForm):
    class Meta:
        model = Attachment
        fields = ["file"]


#-----------------------------------------OTP Form-----------------------------------------------------------------------#

class OTPLoginRequestForm(forms.Form):
    email = forms.EmailField(label="Work email")


class OTPVerifyForm(forms.Form):
    email = forms.EmailField(label="Work email")
    code = forms.CharField(
        label="OTP code",
        max_length=6,
        widget=forms.TextInput(attrs={"autocomplete": "one-time-code"})
    )


#--------------------------------------USE WITH EMAIL CREATING------------------------------------------------------#

User = get_user_model()


class InviteUserForm(forms.Form):
    email = forms.EmailField(label="Work email")
    full_name = forms.CharField(
        label="Full name (optional)",
        required=False,
    )
    role = forms.ChoiceField(
        label="Role",
        choices=Profile.ROLE_CHOICES,
    )
    department = forms.ChoiceField(
        label="Department",
        choices=[("", "---------")] + list(Profile.DEPARTMENT_CHOICES),
        required=False,
    )

    def clean_email(self):
        email = self.cleaned_data["email"].lower().strip()
        # Optional: same domain restriction as OTP
        allowed_domains = {"garagecollective.ag", "garagecollective.agency"}
        domain = email.split("@")[-1]
        if domain not in allowed_domains:
            raise forms.ValidationError("Please use a company email address.")
        return email
    
#--------------------------Edit Members -----------------------------------------#

class ProjectMembersForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ["members"]
        widgets = {
            "members": forms.SelectMultiple(attrs={"size": 8}),
        }
