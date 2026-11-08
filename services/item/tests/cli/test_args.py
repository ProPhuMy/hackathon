"""Argument parsing and subcommand dispatch of `python -m src`."""
from unittest.mock import patch

from src.cli import main, parse_args


def test_record_cli_arg_parsing():
    args = parse_args(["record", "http://localhost:8080/video", "out.mp4"])
    assert args.subcommand == "record"
    assert args.url == "http://localhost:8080/video"
    assert args.out == "out.mp4"


def test_calibrate_parser():
    args = parse_args(["calibrate", "http://localhost:8080/video"])
    assert args.subcommand == "calibrate"
    assert args.source == "http://localhost:8080/video"
    assert args.out == "config.json"

    args2 = parse_args(["calibrate", "clip.mp4", "--out", "my_config.json"])
    assert args2.source == "clip.mp4"
    assert args2.out == "my_config.json"


def test_calibrate_main_dispatch():
    with patch("src.cli.calibrate_command") as mock_cal:
        main(["calibrate", "http://camera/stream", "--out", "out.json"])
        mock_cal.assert_called_once_with("http://camera/stream", "out.json")


def test_probe_parser():
    args = parse_args(["probe", "video.mp4", "annotated.mp4"])
    assert args.subcommand == "probe"
    assert args.clip == "video.mp4"
    assert args.out == "annotated.mp4"
    assert args.config == "config.json"

    args_custom = parse_args(["probe", "clip.mp4", "out.mp4", "--config", "custom.json"])
    assert args_custom.clip == "clip.mp4"
    assert args_custom.out == "out.mp4"
    assert args_custom.config == "custom.json"


def test_probe_main_dispatch():
    with patch("src.cli.probe_command") as mock_probe:
        main(["probe", "in.mp4", "out.mp4", "--config", "conf.json"])
        mock_probe.assert_called_once_with(
            clip="in.mp4", out_path="out.mp4", config_path="conf.json", detector="yoloe"
        )


def test_cli_detector_flag():
    args_default = parse_args(["probe", "in.mp4", "out.mp4"])
    assert args_default.detector == "yoloe"

    args_gdino = parse_args(["probe", "in.mp4", "out.mp4", "--detector", "gdino"])
    assert args_gdino.detector == "gdino"

    args_run = parse_args(["run", "--source", "vid.mp4", "--detector", "gdino"])
    assert args_run.detector == "gdino"

    args_eval = parse_args(["evaluate", "--detector", "gdino"])
    assert args_eval.detector == "gdino"


def test_cli_parse_args():

    args = parse_args(["run", "--source", "test.mp4", "--dry-run"])
    assert args.subcommand == "run"
    assert args.source == "test.mp4"
    assert args.config == "config.json"
    assert args.gallery == "data/gallery.json"
    assert args.broker == "localhost:19092"
    assert args.dry_run is True
    assert args.debug_video is None
    assert args.embed is False
    assert args.holding == "box"

    args2 = parse_args(
        [
            "run",
            "--source",
            "http://192.168.1.10:8080/video",
            "--config",
            "custom_cfg.json",
            "--gallery",
            "custom_gallery.json",
            "--broker",
            "10.0.0.1:9092",
            "--debug-video",
            "out.mp4",
            "--embed",
            "--holding",
            "mask",
        ]
    )
    assert args2.source == "http://192.168.1.10:8080/video"
    assert args2.config == "custom_cfg.json"
    assert args2.gallery == "custom_gallery.json"
    assert args2.broker == "10.0.0.1:9092"
    assert args2.dry_run is False
    assert args2.debug_video == "out.mp4"
    assert args2.embed is True
    assert args2.holding == "mask"

    args_eval = parse_args(["evaluate", "--embed"])
    assert args_eval.subcommand == "evaluate"
    assert args_eval.embed is True
    assert args_eval.holding == "box"

    args_eval2 = parse_args(["evaluate", "--holding", "mask"])
    assert args_eval2.subcommand == "evaluate"
    assert args_eval2.holding == "mask"


def test_cli_shelf_check_flags():

    args_run = parse_args(["run", "--source", "vid.mp4", "--shelf-check"])
    assert args_run.shelf_check is True

    args_run_default = parse_args(["run", "--source", "vid.mp4"])
    assert args_run_default.shelf_check is False

    args_eval = parse_args(["evaluate", "--shelf-check"])
    assert args_eval.shelf_check is True

    args_eval_default = parse_args(["evaluate"])
    assert args_eval_default.shelf_check is False
