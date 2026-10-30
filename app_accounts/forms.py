from django import forms
from django.contrib.auth.password_validation import validate_password

from app_backend.forms import BootstrapFormMixin
from app_accounts.models import Role, User


class UserForm(BootstrapFormMixin, forms.ModelForm):
    """FR-21: administrators create, edit, deactivate and manage users."""
    password = forms.CharField(widget=forms.PasswordInput(render_value=False), required=False,
                               help_text='Leave blank to keep the current password.')

    class Meta:
        model = User
        fields = ['username', 'full_name', 'email', 'phone', 'role', 'status']

    def clean_password(self):
        password = self.cleaned_data.get('password')
        if not self.instance.pk and not password:
            raise forms.ValidationError('Password is required for a new user.')
        if password:
            validate_password(password, self.instance)
        return password

    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data.get('password')
        if password:
            user.set_password(password)
        if commit:
            user.save()
        return user


class RoleForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Role
        fields = ['role_name', 'description', 'permissions']
        widgets = {'permissions': forms.CheckboxSelectMultiple}
