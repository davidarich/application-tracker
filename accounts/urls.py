from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("profile/", views.profile, name="profile"),
    path("profile/photo/", views.avatar, name="avatar"),
    path("profile/photo/upload/", views.avatar_upload, name="avatar_upload"),
    path("profile/photo/remove/", views.avatar_remove, name="avatar_remove"),
]
