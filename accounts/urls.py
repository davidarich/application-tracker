from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("profile/", views.profile, name="profile"),
    path("profile/photo/", views.avatar, name="avatar"),
    path("profile/photo/upload/", views.avatar_upload, name="avatar_upload"),
    path("profile/photo/remove/", views.avatar_remove, name="avatar_remove"),
    path("api-tokens/", views.api_tokens, name="api_tokens"),
    path("api-tokens/create/", views.api_token_create, name="api_token_create"),
    path(
        "api-tokens/<uuid:pk>/revoke/",
        views.api_token_revoke,
        name="api_token_revoke",
    ),
]
