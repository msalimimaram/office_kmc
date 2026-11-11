from django.urls import path

from . import views, wizard

urlpatterns = [
    path("", wizard.import_center, name="import_center"),
    path("claims/", wizard.profile_import, {"profile": "claims"}, name="claim_import"),
    path("claims/<int:batch_id>/confirm/", views.claim_import_confirm, name="claim_import_confirm"),
    path("people/", wizard.profile_import, {"profile": "people_roster"}, name="people_import"),
    path("contracts/", wizard.profile_import, {"profile": "contracts"}, name="contract_import"),
    path("batches/<int:batch_id>/confirm/", wizard.profile_import_confirm, name="profile_import_confirm"),
    path("<slug:profile>/template/", wizard.download_profile_template, name="import_template"),
    path("<slug:profile>/", wizard.profile_import, name="profile_import"),
]
