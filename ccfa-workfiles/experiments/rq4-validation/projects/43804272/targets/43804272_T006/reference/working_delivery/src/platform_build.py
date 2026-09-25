HOW_TO = {
    "media_format": "shared_video",
    "media_platforms": ["android", "ios"],
    "delivery_method": "external_streaming",
    "tutorial_images_required": False,
    "video_hosting_channel": "client_main_youtube_channel",
    "video_url": "https://cedar-meadow.example/resource/e0024",
    "integration_status": "ready",
}

PLATFORM_BUILD = {
    "schema_version": "mobile-platform-build-v1",
    "platforms": ["android", "ios"],
    "how_to": HOW_TO,
    "package_policy": {"bundled_tutorial_images": [], "remote_media_excluded_from_package": True},
    "release_gate": "video-resource-configured",
}
