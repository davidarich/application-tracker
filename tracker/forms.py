"""Forms for users managing their own tracker data."""

from typing import ClassVar, cast, final

from django import forms
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.db.models.functions import Lower
from django.http import QueryDict

from accounts.models import User

from .models import (
    Certification,
    Company,
    Contact,
    Education,
    Job,
    Resume,
    Skill,
    WorkExperience,
)
from .ownership import active_skills, companies_for


@final
class CompanyForm(forms.ModelForm):
    """A company the user tracks. The owner is set by the view, never the form."""

    @final
    class Meta:
        model = Company
        fields: ClassVar[list[str]] = [
            "name",
            "website",
            "mission_statement",
            "is_staffing_agency",
        ]
        labels: ClassVar[dict[str, str]] = {"is_staffing_agency": "Staffing agency"}
        help_texts: ClassVar[dict[str, str]] = {
            "website": "For example, https://example.com",
            "mission_statement": "What the company says it's about, e.g. from its About page.",
            "is_staffing_agency": "Tick this for recruiters who hire on behalf of other companies.",
        }
        widgets: ClassVar[dict[str, forms.Widget]] = {
            "name": forms.TextInput(
                attrs={"autofocus": True, "autocomplete": "organization"}
            ),
            "website": forms.URLInput(
                attrs={"placeholder": "https://", "autocomplete": "url"}
            ),
            "mission_statement": forms.Textarea(attrs={"rows": 6, "class": "resize-y"}),
        }


@final
class ContactForm(forms.ModelForm):
    """A contact at one of the user's companies; the company is set by the view."""

    @final
    class Meta:
        model = Contact
        fields: ClassVar[list[str]] = ["name", "email", "phone_number", "linkedin_url"]
        labels: ClassVar[dict[str, str]] = {"linkedin_url": "LinkedIn profile"}
        help_texts: ClassVar[dict[str, str]] = {
            "linkedin_url": "For example, https://www.linkedin.com/in/their-name",
        }
        widgets: ClassVar[dict[str, forms.Widget]] = {
            "name": forms.TextInput(attrs={"autofocus": True, "autocomplete": "off"}),
            "email": forms.EmailInput(attrs={"autocomplete": "off"}),
            "phone_number": forms.TextInput(
                attrs={"type": "tel", "autocomplete": "off"}
            ),
            "linkedin_url": forms.URLInput(attrs={"placeholder": "https://"}),
        }


@final
class JobForm(forms.ModelForm):
    """A job at one of the user's companies; make it with make_job_form()."""

    @final
    class Meta:
        model = Job
        fields: ClassVar[list[str]] = [
            "company",
            "title",
            "posting_url",
            "location_city",
            "location_state",
            "workplace_type",
            "salary_min",
            "salary_max",
            "description",
            "skills",
        ]
        labels: ClassVar[dict[str, str]] = {
            "title": "Job title",
            "posting_url": "Job posting",
            "location_city": "City",
            "location_state": "State / region",
            "salary_min": "Minimum salary",
            "salary_max": "Maximum salary",
        }
        help_texts: ClassVar[dict[str, str]] = {
            "posting_url": "A link to the job ad, e.g. https://example.com/jobs/123",
            "workplace_type": "Choose Not specified if the posting doesn't say.",
            "salary_min": "Yearly, as a whole number, e.g. 120000",
            "salary_max": "Yearly, as a whole number, e.g. 150000",
        }
        widgets: ClassVar[dict[str, forms.Widget]] = {
            "title": forms.TextInput(attrs={"autofocus": True}),
            "posting_url": forms.URLInput(attrs={"placeholder": "https://"}),
            "salary_min": forms.NumberInput(attrs={"min": 0, "step": 1000}),
            "salary_max": forms.NumberInput(attrs={"min": 0, "step": 1000}),
            "description": forms.Textarea(attrs={"rows": 6, "class": "resize-y"}),
            # Enhanced by assets/js/skill-picker.js into a search box with
            # removable labels; a plain multi-select without JavaScript.
            "skills": forms.SelectMultiple(
                attrs={
                    "size": 8,
                    "class": "w-full rounded-xl border border-line bg-raised px-2 py-1.5 text-sm text-ink",
                }
            ),
        }


def make_job_form(
    data: QueryDict | None, user: User, job: Job | None = None
) -> JobForm:
    """A job form (for a new job, or editing `job`) whose company choices are
    only `user`'s own companies, so a job can never be attached to someone
    else's company."""
    form = JobForm(data, instance=job)
    company = cast(forms.ModelChoiceField, form.fields["company"])
    company.queryset = companies_for(user).order_by("name")
    company.empty_label = "Choose a company"
    skills = cast(forms.ModelMultipleChoiceField, form.fields["skills"])
    skills.queryset = active_skills().order_by(Lower("name"))  # ignoring case
    workplace = cast(forms.ChoiceField, form.fields["workplace_type"])
    workplace.choices = [("", "Not specified"), *Job.WorkplaceType.choices]
    return form


@final
class SkillForm(forms.ModelForm):
    """A shared skill (staff only)."""

    @final
    class Meta:
        model = Skill
        fields: ClassVar[list[str]] = ["name", "description"]
        help_texts: ClassVar[dict[str, str]] = {
            "description": "A sentence on what the skill covers.",
        }
        widgets: ClassVar[dict[str, forms.Widget]] = {
            "name": forms.TextInput(attrs={"autofocus": True}),
            "description": forms.Textarea(attrs={"rows": 4, "class": "resize-y"}),
        }

    def clean_name(self) -> str:
        """Skill names are unique ignoring case (excluding the skill being edited)."""
        name = cast(str, self.cleaned_data["name"]).strip()
        skill = cast(Skill, self.instance)
        if active_skills().filter(name__iexact=name).exclude(id=skill.id).exists():
            raise ValidationError("A skill with this name already exists.")
        return name


# --- Resume ------------------------------------------------------------------------

MAX_RESUME_UPLOAD_BYTES = 5 * 1024 * 1024


@final
class ResumeUploadForm(forms.Form):
    """A resume PDF to fill in the resume from. cleaned_data["file"] is its bytes."""

    file = forms.FileField(
        label="Resume (PDF)",
        widget=forms.FileInput(attrs={"accept": ".pdf,application/pdf"}),
    )

    def clean_file(self) -> bytes:
        upload = cast(UploadedFile, self.cleaned_data["file"])
        if (upload.size or 0) > MAX_RESUME_UPLOAD_BYTES:
            raise ValidationError("This file is too big. Upload a PDF of up to 5 MB.")
        data = b"".join(upload.chunks())
        if not (upload.name or "").lower().endswith(".pdf") or not data.startswith(
            b"%PDF"
        ):
            raise ValidationError("Upload a PDF file.")
        return data


class MonthInput(forms.DateInput):
    """A month picker (<input type="month">); a YYYY-MM text box where unsupported."""

    input_type: str = "month"

    def __init__(self) -> None:
        super().__init__(format="%Y-%m", attrs={"placeholder": "YYYY-MM"})


class MonthField(forms.DateField):
    """A date entered as a month (YYYY-MM), stored as the first of that month."""

    widget: type[forms.Widget] | forms.Widget = MonthInput
    input_formats: tuple[str, ...] = ("%Y-%m", "%Y-%m-%d")


def textarea(rows: int = 5) -> forms.Textarea:
    return forms.Textarea(attrs={"rows": rows, "class": "resize-y"})


@final
class ResumeSummaryForm(forms.ModelForm):
    @final
    class Meta:
        model = Resume
        fields: ClassVar[list[str]] = ["summary"]
        help_texts: ClassVar[dict[str, str]] = {
            "summary": "A few sentences on who you are, what you do and what you're looking for.",
        }
        widgets: ClassVar[dict[str, forms.Widget]] = {"summary": textarea(6)}


@final
class ResumeSkillsForm(forms.ModelForm):
    """The resume's skills, picked from the shared list."""

    @final
    class Meta:
        model = Resume
        fields: ClassVar[list[str]] = ["skills"]
        widgets: ClassVar[dict[str, forms.Widget]] = {
            # Enhanced by assets/js/skill-picker.js, as on the job form.
            "skills": forms.SelectMultiple(
                attrs={
                    "size": 8,
                    "class": "w-full rounded-xl border border-line bg-raised px-2 py-1.5 text-sm text-ink",
                }
            ),
        }

    def __init__(
        self, data: QueryDict | None = None, instance: Resume | None = None
    ) -> None:
        super().__init__(data, instance=instance)
        skills = cast(forms.ModelMultipleChoiceField, self.fields["skills"])
        skills.queryset = active_skills().order_by(Lower("name"))  # ignoring case


@final
class WorkExperienceForm(forms.ModelForm):
    # Shown full width on the entry form (text areas always are).
    wide_fields: ClassVar[frozenset[str]] = frozenset({"location"})

    @final
    class Meta:
        model = WorkExperience
        fields: ClassVar[list[str]] = [
            "title",
            "employer",
            "start_date",
            "end_date",
            "location",
            "description",
        ]
        field_classes: ClassVar[dict[str, type[forms.Field]]] = {
            "start_date": MonthField,
            "end_date": MonthField,
        }
        labels: ClassVar[dict[str, str]] = {"description": "What you did"}
        help_texts: ClassVar[dict[str, str]] = {
            "location": "For example, Austin, TX or Remote",
            "employer": "Leave empty for a career break, like a sabbatical or medical leave.",
            "end_date": "Leave empty if you still work here.",
            "description": "Responsibilities and achievements, one per line, each starting with “- ”.",
        }
        widgets: ClassVar[dict[str, forms.Widget]] = {
            "title": forms.TextInput(attrs={"autofocus": True}),
            "description": textarea(),
        }


@final
class EducationForm(forms.ModelForm):
    wide_fields: ClassVar[frozenset[str]] = frozenset({"institution", "in_progress"})

    @final
    class Meta:
        model = Education
        fields: ClassVar[list[str]] = [
            "institution",
            "degree",
            "field_of_study",
            "start_date",
            "end_date",
            "in_progress",
            "description",
        ]
        field_classes: ClassVar[dict[str, type[forms.Field]]] = {
            "start_date": MonthField,
            "end_date": MonthField,
        }
        labels: ClassVar[dict[str, str]] = {
            "institution": "School",
            "end_date": "End date (or expected)",
            "description": "Details",
        }
        help_texts: ClassVar[dict[str, str]] = {
            "degree": "For example, Bachelor of Science",
            "field_of_study": "For example, Computer Science",
            "in_progress": "Tick if you're still studying. The end date is when you expect to finish.",
            "description": "Honors, activities or coursework.",
        }
        widgets: ClassVar[dict[str, forms.Widget]] = {
            "institution": forms.TextInput(attrs={"autofocus": True}),
            "in_progress": forms.CheckboxInput(
                attrs={
                    "class": "mt-0.5 size-4 shrink-0 cursor-pointer rounded accent-accent"
                }
            ),
            "description": textarea(),
        }


@final
class CertificationForm(forms.ModelForm):
    wide_fields: ClassVar[frozenset[str]] = frozenset({"in_progress"})

    @final
    class Meta:
        model = Certification
        fields: ClassVar[list[str]] = [
            "name",
            "issuer",
            "issued_on",
            "expires_on",
            "in_progress",
            "credential_id",
            "credential_url",
        ]
        field_classes: ClassVar[dict[str, type[forms.Field]]] = {
            "issued_on": MonthField,
            "expires_on": MonthField,
        }
        help_texts: ClassVar[dict[str, str]] = {
            "name": "For example, AWS Certified Solutions Architect",
            "expires_on": "Leave empty if it doesn't expire.",
            "in_progress": "Tick if you're still working towards it. The issue date is when you expect to finish.",
            "credential_url": "A link where others can verify it.",
        }
        labels: ClassVar[dict[str, str]] = {"issued_on": "Issue date (or expected)"}
        widgets: ClassVar[dict[str, forms.Widget]] = {
            "name": forms.TextInput(attrs={"autofocus": True}),
            "in_progress": forms.CheckboxInput(
                attrs={
                    "class": "mt-0.5 size-4 shrink-0 cursor-pointer rounded accent-accent"
                }
            ),
            "credential_url": forms.URLInput(attrs={"placeholder": "https://"}),
        }
