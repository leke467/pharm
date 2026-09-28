from django.urls import path
from .views import (
    SyncUploadView,
    SyncDownloadView,
    BranchBackupUploadView,
    BranchBackupListView,
    BranchBackupDownloadView,
)

urlpatterns = [
    path('sync/upload/', SyncUploadView.as_view(), name='sync-upload'),
    path('sync/download/', SyncDownloadView.as_view(), name='sync-download'),
    path('sync/backups/', BranchBackupListView.as_view(), name='sync-branch-backups-list'),
    path('sync/backups/upload/', BranchBackupUploadView.as_view(), name='sync-branch-backups-upload'),
    path('sync/backups/<uuid:backup_id>/download/', BranchBackupDownloadView.as_view(), name='sync-branch-backups-download'),
]

