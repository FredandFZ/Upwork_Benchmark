HOW_TO = {
    "media_format": "youtube_video",
    "media_platforms": ["ios"],
    "delivery_method": "external_streaming",
    "tutorial_images_required": False,
    "video_url": None,
    "integration_status": "awaiting-video-resource",
}

PLATFORM_BUILD = {
    "schema_version": "mobile-platform-build-v1",
    "platforms": ["android", "ios"],
    "how_to": HOW_TO,
    "package_policy": {"bundled_tutorial_images": [], "remote_media_excluded_from_package": True},
    "ios_packaging": {"optimization_priority": "smallest-possible-app-size"},
}
