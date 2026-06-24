from pathlib import Path

import yaml

from hackster_studio.automation.movie_pipeline import MovieBuildOptions, MovieBuildPipeline


def test_movie_package_creates_shots_prompts_audio_and_edit_files(tmp_path: Path) -> None:
    movie_yaml = tmp_path / "movies" / "password_dragon_teaser" / "movie.yaml"
    result = MovieBuildPipeline(
        movie_yaml=movie_yaml,
        options=MovieBuildOptions(limit_shots=3),
    ).run()

    movie_root = movie_yaml.parent

    assert result.shot_count == 3
    assert movie_yaml.exists()
    assert len(list((movie_root / "shots").glob("SH*.yaml"))) == 3
    assert len(list((movie_root / "prompts" / "keyframes").glob("SH*_keyframe.md"))) == 3
    assert len(list((movie_root / "prompts" / "video").glob("SH*_video.md"))) == 3
    assert (movie_root / "audio" / "dialogue" / "SH020_dialogue.txt").exists()
    assert (movie_root / "audio" / "sfx" / "SH010_sfx.md").exists()
    assert (movie_root / "audio" / "music" / "music_brief.md").exists()
    assert (movie_root / "edit" / "edit_decision_list.csv").exists()
    assert (movie_root / "edit" / "assemble_ffmpeg.sh").exists()
    assert (movie_root / "review" / "SH010_review.md").exists()
    assert (movie_root / "reports" / "model_handoff.md").exists()

    shot = yaml.safe_load((movie_root / "shots" / "SH020.yaml").read_text(encoding="utf-8"))
    assert shot["video_raw_path"].endswith("SH020_raw.mp4")
    assert shot["video_lipsynced_path"].endswith("SH020_lipsync.mp4")
    assert shot["dialogue_audio_path"].endswith("SH020_dialogue.wav")

    prompt = (movie_root / "prompts" / "video" / "SH020_video.md").read_text(encoding="utf-8")
    assert "Animate this shot from the approved keyframe." in prompt
    assert "Every problem has a clever fix!" in prompt
    assert "LOCKED CHARACTER MODEL" in prompt
