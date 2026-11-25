from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = (
        "Retired: create the technical Django superuser first, then designate "
        "the first operational System Admin from the restricted Django admin screen."
    )

    def handle(self, *args, **options):
        raise CommandError(
            "این فرمان بازنشسته شده است. ابتدا حساب فنی را با "
            "'python manage.py createsuperuser' ایجاد کنید؛ سپس با همان حساب وارد "
            "/admin/ شوید و از بخش «انتصاب‌های دسترسی» فقط نخستین مدیر سامانه را "
            "انتخاب کنید. پس از ثبت این انتصاب، دسترسی حساب سوپریوزر به پنل مدیریت "
            "عملیاتی به‌طور خودکار بسته می‌شود."
        )
