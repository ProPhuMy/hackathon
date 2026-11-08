"""Command-line interface: `python -m src <record|calibrate|probe|run|evaluate>`, one module per command."""
import argparse

from .calibrate import calibrate_command
from .evaluate import evaluate_command
from .probe import probe_command
from .record import record_command
from .run import run_command


def _add_config(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config",
        default="config.json",
        help="Path to config JSON (default: config.json)",
    )


def _add_detector(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--detector",
        choices=["yoloe", "gdino"],
        default="yoloe",
        help="Detector to use: yoloe or gdino (default: yoloe)",
    )


def _add_pipeline_options(parser: argparse.ArgumentParser) -> None:
    """Flags shared by `run` and `evaluate`, in their help order."""
    parser.add_argument(
        "--embed",
        action="store_true",
        help="Use visual embeddings and Hungarian matching",
    )
    parser.add_argument(
        "--holding",
        choices=["box", "mask"],
        default="box",
        help="Holding detection method: box overlap or SAM 2 mask overlap (default: box)",
    )
    _add_detector(parser)
    parser.add_argument(
        "--shelf-check",
        action="store_true",
        help="Enable shelf before/after second opinion",
    )


def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="fridge-item", description="Fridge Tracker item-recognition service"
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    record_parser = subparsers.add_parser("record", help="Record video stream to MP4")
    record_parser.add_argument("url", help="HTTP stream URL or video path")
    record_parser.add_argument("out", help="Output MP4 file path")

    calibrate_parser = subparsers.add_parser(
        "calibrate", help="Calibrate fridge ROI, door line, and brightness thresholds"
    )
    calibrate_parser.add_argument("source", help="HTTP stream URL or video path")
    calibrate_parser.add_argument(
        "--out",
        default="config.json",
        help="Output config JSON path (default: config.json)",
    )

    probe_parser = subparsers.add_parser(
        "probe", help="Run detector and overlay on clip"
    )
    probe_parser.add_argument("clip", help="Input video clip path or stream URL")
    probe_parser.add_argument("out", help="Output overlay video MP4 path")
    _add_config(probe_parser)
    _add_detector(probe_parser)

    run_parser = subparsers.add_parser("run", help="Run item recognition pipeline")
    run_parser.add_argument(
        "--source", required=True, help="HTTP stream URL or video path"
    )
    _add_config(run_parser)
    run_parser.add_argument(
        "--gallery",
        default="data/gallery.json",
        help="Path to gallery JSON (default: data/gallery.json)",
    )
    run_parser.add_argument(
        "--broker",
        default="localhost:19092",
        help="Kafka broker address (default: localhost:19092)",
    )
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print events only, do not publish to Kafka",
    )
    run_parser.add_argument(
        "--debug-video",
        default=None,
        help="Output overlay video MP4 path",
    )
    _add_pipeline_options(run_parser)

    evaluate_parser = subparsers.add_parser(
        "evaluate", help="Evaluate item recognition pipeline against labeled clips"
    )
    evaluate_parser.add_argument(
        "--labels",
        default="data/labels.csv",
        help="Path to labels CSV (default: data/labels.csv)",
    )
    evaluate_parser.add_argument(
        "--clips",
        default="data/clips",
        help="Path to directory containing clips (default: data/clips)",
    )
    _add_config(evaluate_parser)
    _add_pipeline_options(evaluate_parser)

    return parser.parse_args(args)


def main(args: list[str] | None = None) -> None:
    parsed = parse_args(args)
    if parsed.subcommand == "record":
        record_command(parsed.url, parsed.out)
    elif parsed.subcommand == "calibrate":
        calibrate_command(parsed.source, parsed.out)
    elif parsed.subcommand == "probe":
        probe_command(
            clip=parsed.clip,
            out_path=parsed.out,
            config_path=parsed.config,
            detector=parsed.detector,
        )
    elif parsed.subcommand == "run":
        run_command(
            source=parsed.source,
            config_path=parsed.config,
            gallery_path=parsed.gallery,
            broker=parsed.broker,
            dry_run=parsed.dry_run,
            debug_video=parsed.debug_video,
            embed=parsed.embed,
            holding=parsed.holding,
            detector=parsed.detector,
            shelf_check=parsed.shelf_check,
        )
    elif parsed.subcommand == "evaluate":
        evaluate_command(
            labels_path=parsed.labels,
            clips_dir=parsed.clips,
            config_path=parsed.config,
            embed=parsed.embed,
            holding=parsed.holding,
            detector=parsed.detector,
            shelf_check=parsed.shelf_check,
        )
