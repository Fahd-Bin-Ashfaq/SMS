from django import forms

from apps.academics.models import Student


MAX_PHOTO_BYTES = 2 * 1024 * 1024


class StudentProfileForm(forms.ModelForm):
    """Details a student may change themselves; identity fields stay with the office."""

    class Meta:
        model = Student
        fields = ("photo", "email", "phone", "address", "area")
        widgets = {"photo": forms.FileInput(attrs={"accept": "image/*"})}

    def clean_photo(self):
        photo = self.cleaned_data.get("photo")
        if photo and getattr(photo, "size", 0) > MAX_PHOTO_BYTES:
            raise forms.ValidationError("The photo must be 2 MB or smaller.")
        return photo
