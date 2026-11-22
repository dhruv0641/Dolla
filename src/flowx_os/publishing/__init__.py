"""Official-platform publishing boundaries."""

from flowx_os.publishing.instagram import (
    INSTAGRAM_BASIC_SCOPE,
    INSTAGRAM_PUBLISH_SCOPE,
    InstagramAccountType,
    InstagramAuthorization,
    InstagramContainer,
    InstagramContainerState,
    InstagramContainerStatus,
    InstagramError,
    InstagramPolicy,
    InstagramPublicationClaim,
    InstagramPublicationResult,
    InstagramPublishedMedia,
    InstagramPublisher,
    InstagramPublishRequest,
    InstagramRemoteMedia,
)

from flowx_os.publishing.youtube import (
    YOUTUBE_UPLOAD_SCOPE,
    YouTubeAuthorization,
    YouTubeError,
    YouTubePolicy,
    YouTubePrivacy,
    YouTubePublicationClaim,
    YouTubePublicationResult,
    YouTubePublisher,
    YouTubePublishRequest,
    YouTubeRemoteVideo,
    YouTubeUploadOutcome,
    YouTubeUploadState,
)

__all__ = [
    "INSTAGRAM_BASIC_SCOPE", "INSTAGRAM_PUBLISH_SCOPE", "InstagramAccountType",
    "InstagramAuthorization", "InstagramContainer", "InstagramContainerState",
    "InstagramContainerStatus", "InstagramError", "InstagramPolicy",
    "InstagramPublicationClaim", "InstagramPublicationResult", "InstagramPublishedMedia",
    "InstagramPublisher", "InstagramPublishRequest", "InstagramRemoteMedia",
    "YOUTUBE_UPLOAD_SCOPE", "YouTubeAuthorization", "YouTubeError",
    "YouTubePolicy", "YouTubePrivacy", "YouTubePublicationClaim",
    "YouTubePublicationResult", "YouTubePublisher", "YouTubePublishRequest",
    "YouTubeRemoteVideo", "YouTubeUploadOutcome", "YouTubeUploadState",
]
