from django import forms
from django.contrib.auth.password_validation import validate_password

from .models import Camera, RecognitionSettings, Room, SchoolClass, Student, TeacherAssignment, User


class StartSessionForm(forms.Form):
    assignment = forms.ModelChoiceField(queryset=TeacherAssignment.objects.none(), label="Sinf va xona")
    pilot_blind = forms.BooleanField(
        required=False,
        label="Pilot: avval mustaqil yoʻqlama",
        help_text="Kamera natijasi siz qoʻlda yoʻqlama qilib boʻlguncha koʻrsatilmaydi",
    )

    def __init__(self, *args, teacher=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assignment"].queryset = TeacherAssignment.objects.filter(teacher=teacher).select_related(
            "school_class", "room"
        )
        self.fields["assignment"].label_from_instance = lambda a: f"{a.school_class} — {a.room}"
        self.fields["assignment"].empty_label = "Sinf va xonani tanlang"
        qs = self.fields["assignment"].queryset
        if len(qs) == 1:  # yagona biriktiruv — darhol tanlangan
            self.fields["assignment"].initial = qs[0].pk


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleImageField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput(attrs={"accept": "image/jpeg,image/png"}))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single = super().clean
        if isinstance(data, (list, tuple)):
            return [single(d, initial) for d in data]
        return [single(data, initial)]


class SampleUploadForm(forms.Form):
    images = MultipleImageField(label="Yuz rasmlari (3–5 ta, turli burchakdan)")


class ObservationUploadForm(forms.Form):
    file = forms.FileField(label="Toʻldirilgan shablon (CSV)")


# ---------------------------------------------------------------------------
# Boshqaruv (administrator) formalari
# ---------------------------------------------------------------------------

class RoomForm(forms.ModelForm):
    class Meta:
        model = Room
        fields = ("name",)


class CameraForm(forms.ModelForm):
    rtsp_url = forms.CharField(
        label="RTSP manzil yoki kamera raqami",
        required=False,
        widget=forms.TextInput(attrs={"autocomplete": "off", "placeholder": "rtsp://login:parol@192.168.1.10:554/stream  yoki  0"}),
        help_text="Kompyuter kamerasi uchun 0 (ikkinchi kamera — 1). Manzil shifrlangan holda saqlanadi va qayta "
        "koʻrsatilmaydi; oʻzgartirmaslik uchun boʻsh qoldiring.",
    )

    class Meta:
        model = Camera
        fields = ("room", "name", "rtsp_url", "is_active")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["room"].empty_label = "Xonani tanlang"

    def clean_rtsp_url(self):
        v = self.cleaned_data.get("rtsp_url", "").strip()
        if v and not (v.lower().startswith(("rtsp://", "rtsps://")) or v.isdigit()):
            raise forms.ValidationError("Manzil rtsp:// bilan boshlanishi yoki kamera raqami (0, 1…) boʻlishi kerak")
        if not v and not (self.instance and self.instance.rtsp_url_encrypted):
            raise forms.ValidationError("Manzil kiritilishi shart")
        return v

    def save(self, commit=True):
        obj = super().save(commit=False)
        if self.cleaned_data.get("rtsp_url"):
            obj.rtsp_url = self.cleaned_data["rtsp_url"]
        if commit:
            obj.save()
        return obj


class SchoolClassForm(forms.ModelForm):
    class Meta:
        model = SchoolClass
        fields = ("name", "academic_year")


class StudentForm(forms.ModelForm):
    class Meta:
        model = Student
        fields = ("last_name", "first_name", "middle_name", "school_class", "student_code", "is_active")
        widgets = {
            "last_name": forms.TextInput(attrs={"autofocus": True, "placeholder": "masalan: Aliyev"}),
            "first_name": forms.TextInput(attrs={"placeholder": "masalan: Vali"}),
            "middle_name": forms.TextInput(attrs={"placeholder": "ixtiyoriy"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["school_class"].empty_label = "Sinfni tanlang"
        self.fields["student_code"].required = False


class StudentImportForm(forms.Form):
    school_class = forms.ModelChoiceField(queryset=SchoolClass.objects.all(), label="Sinf")
    file = forms.FileField(
        label="CSV fayl",
        help_text="Har qatorda: Familiya;Ism;Otasining ismi (oxirgisi ixtiyoriy) yoki bitta katakda «Familiya Ism»",
    )


class UserCreateForm(forms.ModelForm):
    password1 = forms.CharField(label="Parol", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    password2 = forms.CharField(label="Parolni takrorlang", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    class Meta:
        model = User
        fields = ("username", "first_name", "last_name", "role")

    def clean(self):
        data = super().clean()
        p1, p2 = data.get("password1"), data.get("password2")
        if p1 and p1 != p2:
            self.add_error("password2", "Parollar mos emas")
        elif p1:
            try:
                validate_password(p1, self.instance)
            except forms.ValidationError as e:
                self.add_error("password1", e)
        return data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


class UserEditForm(forms.ModelForm):
    new_password = forms.CharField(
        label="Yangi parol", required=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="Oʻzgartirmaslik uchun boʻsh qoldiring",
    )

    class Meta:
        model = User
        fields = ("username", "first_name", "last_name", "role", "is_active")

    def __init__(self, *args, current_user=None, **kwargs):
        self.current_user = current_user
        super().__init__(*args, **kwargs)

    def clean(self):
        data = super().clean()
        if self.current_user and self.instance.pk == self.current_user.pk:
            if data.get("role") != User.Role.ADMIN or not data.get("is_active"):
                raise forms.ValidationError("Oʻzingizni administrator rolidan chiqara yoki bloklay olmaysiz")
        pw = data.get("new_password")
        if pw:
            try:
                validate_password(pw, self.instance)
            except forms.ValidationError as e:
                self.add_error("new_password", e)
        return data

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.cleaned_data.get("new_password"):
            user.set_password(self.cleaned_data["new_password"])
        if commit:
            user.save()
        return user


class AssignmentForm(forms.ModelForm):
    class Meta:
        model = TeacherAssignment
        fields = ("teacher", "school_class", "room")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["teacher"].queryset = User.objects.filter(role=User.Role.TEACHER, is_active=True)
        self.fields["teacher"].label_from_instance = lambda u: u.display_name
        self.fields["teacher"].empty_label = "Oʻqituvchini tanlang"
        self.fields["school_class"].empty_label = "Sinfni tanlang"
        self.fields["room"].empty_label = "Xonani tanlang"


class RecognitionSettingsForm(forms.ModelForm):
    class Meta:
        model = RecognitionSettings
        exclude = ()

    GROUPS = (
        ("Moslikni tasdiqlash qoidasi",
         ("sim_threshold", "margin_delta", "confirm_frames", "confirm_window_seconds", "uncertain_threshold")),
        ("Kadrdagi yuz sifati", ("det_score_threshold", "min_face_px", "min_blur_var", "max_yaw_deg")),
        ("Andoza yaratish", ("enroll_min_samples", "enroll_max_samples", "enroll_min_face_px",
                             "enroll_min_blur_var", "enroll_max_yaw_deg")),
        ("Ishlash", ("max_fps", "detect_max_width", "visibility_gap_seconds", "session_max_minutes",
                     "reconnect_max_seconds")),
    )

    def groups(self):
        return [(title, [self[f] for f in fields]) for title, fields in self.GROUPS]
