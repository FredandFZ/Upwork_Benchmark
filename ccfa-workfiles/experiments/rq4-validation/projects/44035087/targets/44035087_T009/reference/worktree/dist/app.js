for (const video of document.querySelectorAll("video")) {
  video.addEventListener("play", () => video.closest(".media-card").dataset.playing = "true");
  video.addEventListener("pause", () => video.closest(".media-card").dataset.playing = "false");
}

