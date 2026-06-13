from django.urls import include, path

from accounts.admin_views import (
    AdminGrantDeleteView,
    AdminUserDetailView,
    AdminUserGrantListCreateView,
    AdminUserListCreateView,
)
from accounts.auth_views import (
    CsrfView,
    LoginView,
    LogoutView,
    MeView,
    PasswordChangeView,
)

auth_urlpatterns = [
    path("csrf/", CsrfView.as_view(), name="auth-csrf"),
    path("login/", LoginView.as_view(), name="auth-login"),
    path("logout/", LogoutView.as_view(), name="auth-logout"),
    path("me/", MeView.as_view(), name="auth-me"),
    path("password/", PasswordChangeView.as_view(), name="auth-password"),
]

admin_urlpatterns = [
    path("users/", AdminUserListCreateView.as_view(), name="admin-user-list"),
    path("users/<uuid:user_id>/", AdminUserDetailView.as_view(), name="admin-user-detail"),
    path(
        "users/<uuid:user_id>/grants/",
        AdminUserGrantListCreateView.as_view(),
        name="admin-user-grants",
    ),
    path("grants/<uuid:grant_id>/", AdminGrantDeleteView.as_view(), name="admin-grant-delete"),
]

urlpatterns = [
    path("auth/", include(auth_urlpatterns)),
    path("admin/", include(admin_urlpatterns)),
]
