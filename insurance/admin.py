from django.contrib import admin
from .models import Insurer, Contract, ContractRevision

admin.site.register(Insurer)
admin.site.register(Contract)
admin.site.register(ContractRevision)
