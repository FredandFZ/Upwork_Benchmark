PLATFORM_BUILD = {
    "schema_version": "mobile-platform-build-v1",
    "platforms": ["android", "ios"],
    "optimization_priority": "smallest-possible-app-size",
    "localization_coverage": {"android_language_count": 77, "ios_language_count": 40},
    "asset_strategy": {
        "localized_tutorial_images": False,
        "shared_background": "tutorial-background.svg",
        "translatable_text_rendered_by_app": True,
    },
    "android_packaging": {
        "format": "aab",
        "language_splits": True,
        "density_splits": True,
        "minify_enabled": True,
        "shrink_resources": True,
    },
    "ios_packaging": {
        "asset_catalog": True,
        "dead_code_stripping": True,
        "strip_swift_symbols": True,
    },
}
