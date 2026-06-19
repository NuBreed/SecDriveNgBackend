from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q


class EmailPhoneOrUsernameBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        User = get_user_model()
        identifier = username or kwargs.get('email') or kwargs.get('phone')
        if identifier is None or password is None:
            return None

        try:
            user = User.objects.get(
                Q(username__iexact=identifier)
                | Q(email__iexact=identifier)
                | Q(phone=identifier)
            )
        except User.DoesNotExist:
            return None
        except User.MultipleObjectsReturned:
            # Prefer an exact username match if the value collides.
            user = User.objects.filter(username__iexact=identifier).first()
            if user is None:
                return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
