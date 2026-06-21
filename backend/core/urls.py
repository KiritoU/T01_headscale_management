from django.urls import path

from core.views import HealthView, PublicConfigView

urlpatterns = [
    path("config/", PublicConfigView.as_view(), name="public-config"),
    path("health/", HealthView.as_view(), name="health"),
]
