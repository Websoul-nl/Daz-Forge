import gzip
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from forge.pose_converter.converter import convert_g8f_pose_to_g9
from forge.pose_converter.duf import load_duf, save_duf
from forge.pose_converter.product import build_converted_pose_dim_package, convert_pose_product


SAMPLES = Path("D:/Software projects/daz-forge/.codex-local/dim-samples")
ROAD_TRIP_ZIP = SAMPLES / "IM00083577-01_RoadTripPosesforGenesis8Female.zip"
ROAD_TRIP_G8_PATH = "Content/People/Genesis 8 Female/Poses/Road Trip Poses for Genesis 8 Female/Road Trip 01.duf"
ROAD_TRIP_G9_PATH = SAMPLES / "Road Trip 01 G9.duf"


def test_load_and_save_plain_and_gzip_duf_round_trip(tmp_path: Path) -> None:
    pose = {
        "file_version": "0.6.0.0",
        "asset_info": {"type": "preset_pose"},
        "scene": {"animations": []},
    }
    plain_path = tmp_path / "plain.duf"
    gzip_path = tmp_path / "compressed.duf"

    save_duf(pose, plain_path, compressed=False)
    save_duf(pose, gzip_path, compressed=True)

    assert load_duf(plain_path) == pose
    assert load_duf(gzip_path) == pose
    assert gzip.decompress(gzip_path.read_bytes()).startswith(b"{")


def test_convert_road_trip_01_matches_key_g9_calibration_values() -> None:
    _require_road_trip_samples()
    source = _load_road_trip_g8_pose()
    calibration = load_duf(ROAD_TRIP_G9_PATH)

    result = convert_g8f_pose_to_g9(source)
    converted = _meaningful_animation_map(result.pose)
    expected = _meaningful_animation_map(calibration)

    expected_values = {
        ("l_shin", "rotation", "x"): expected[("l_shin", "rotation", "x")],
        ("l_thigh", "rotation", "x"): expected[("l_thigh", "rotation", "x")],
        ("l_thigh", "rotation", "y"): expected[("l_thigh", "rotation", "y")],
        ("l_thigh", "rotation", "z"): expected[("l_thigh", "rotation", "z")],
        ("r_thigh", "rotation", "z"): expected[("r_thigh", "rotation", "z")],
        ("l_foot", "rotation", "x"): expected[("l_foot", "rotation", "x")],
        ("l_forearm", "rotation", "y"): expected[("l_forearm", "rotation", "y")],
        ("l_upperarm", "rotation", "x"): expected[("l_upperarm", "rotation", "x")],
        ("l_shoulder", "rotation", "x"): expected[("l_shoulder", "rotation", "x")],
        ("neck1", "rotation", "y"): expected[("neck1", "rotation", "y")],
        ("neck2", "rotation", "y"): expected[("neck2", "rotation", "y")],
        ("spine1", "rotation", "x"): expected[("spine1", "rotation", "x")],
        ("spine2", "rotation", "x"): expected[("spine2", "rotation", "x")],
    }

    for key, value in expected_values.items():
        assert converted[key] == pytest.approx(value, abs=0.00001)


def test_convert_road_trip_01_writes_lean_pose_without_default_clutter() -> None:
    _require_road_trip_samples()
    result = convert_g8f_pose_to_g9(_load_road_trip_g8_pose())
    animations = result.pose["scene"]["animations"]

    assert len(animations) < 150
    assert result.converted_channels >= 90
    assert not any(
        animation["url"].endswith(":?scale/x/value") and animation["keys"] == [[0, 1]]
        for animation in animations
    )
    assert "lSmallToe4_2" in result.unmapped_bones


def test_convert_pose_product_zip_writes_g9_output_folder_and_report(tmp_path: Path) -> None:
    _require_road_trip_samples()
    output_dir = tmp_path / "converted"

    report = convert_pose_product(ROAD_TRIP_ZIP, output_dir)

    converted_pose = (
        output_dir
        / "Content"
        / "People"
        / "Genesis 9"
        / "Poses"
        / "Road Trip Poses for Genesis 9"
        / "Road Trip 01.duf"
    )
    converted_thumbnail = converted_pose.with_suffix(".duf.png")
    converted_tip = converted_pose.with_name("Road Trip 01.tip.png")
    report_path = output_dir / "pose_conversion_report.json"

    assert report.converted_count == 24
    assert report.skipped_count == 0
    assert converted_pose.exists()
    assert converted_thumbnail.exists()
    assert converted_tip.exists()
    assert report_path.exists()
    assert load_duf(converted_pose)["asset_info"]["type"] == "preset_pose"
    assert "Genesis%209" in load_duf(converted_pose)["asset_info"]["id"]

    report_payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert report_payload["converted_count"] == 24
    assert report_payload["outputs"][0]["source_path"].endswith("Road Trip 01.duf")
    assert "People/Genesis 9/Poses/Road Trip Poses for Genesis 9/Road Trip 01.duf" in {
        item["output_path"] for item in report_payload["outputs"]
    }


def test_convert_pose_product_folder_source(tmp_path: Path) -> None:
    _require_road_trip_samples()
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "converted"
    with ZipFile(ROAD_TRIP_ZIP) as archive:
        archive.extractall(source_dir)

    report = convert_pose_product(source_dir, output_dir)

    assert report.converted_count == 24
    assert (
        output_dir
        / "Content"
        / "People"
        / "Genesis 9"
        / "Poses"
        / "Road Trip Poses for Genesis 9"
        / "Road Trip 24.duf"
    ).exists()


def test_build_converted_pose_dim_package_writes_dim_zip(tmp_path: Path) -> None:
    _require_road_trip_samples()
    output_dir = tmp_path / "packages"

    result = build_converted_pose_dim_package(
        ROAD_TRIP_ZIP,
        output_dir,
        metadata={
            "product_name": "Road Trip Poses for Genesis 9",
            "store_display_name": "Websoul",
            "store_id": "WEBSOUL",
            "store_prefix": "WEB",
            "product_token": "24156031",
            "global_id": "11111111-2222-4333-8444-555555555555",
            "artists": ["Websoul"],
            "primary_artist": "Websoul",
        },
    )

    assert result.conversion_report.converted_count == 24
    assert result.package.zip_path.name == "WEB24156031-01_RoadTripPosesforGenesis9.zip"
    assert result.package.report_path.exists()
    assert result.converted_folder.exists()

    with ZipFile(result.package.zip_path) as archive:
        names = set(archive.namelist())
        converted_pose = (
            "Content/People/Genesis 9/Poses/"
            "Road Trip Poses for Genesis 9/Road Trip 01.duf"
        )
        assert "Manifest.dsx" in names
        assert "Supplement.dsx" in names
        assert converted_pose in names
        assert (
            "Content/People/Genesis 8 Female/Poses/"
            "Road Trip Poses for Genesis 8 Female/Road Trip 01.duf"
        ) not in names
        assert "Content/Runtime/Support/WEBSOUL_24156031_Road_Trip_Poses_for_Genesis_9.dsx" in names
        assert "Content/Runtime/Support/WEBSOUL_24156031_Road_Trip_Poses_for_Genesis_9.dsa" in names
        assert "Content/Runtime/Support/WEBSOUL_24156031_Road_Trip_Poses_for_Genesis_9.jpg" in names

        support = archive.read(
            "Content/Runtime/Support/WEBSOUL_24156031_Road_Trip_Poses_for_Genesis_9.dsx"
        ).decode("utf-8")
        support_script = archive.read(
            "Content/Runtime/Support/WEBSOUL_24156031_Road_Trip_Poses_for_Genesis_9.dsa"
        ).decode("utf-8")
        assert '<Product VALUE="Road Trip Poses for Genesis 9">' in support
        assert f'<Asset VALUE="/{converted_pose.removeprefix("Content/")}">' in support
        assert '<ContentType VALUE="Preset/Pose"/>' in support
        assert '<Compatibility VALUE="/Genesis 9/Base"/>' in support
        assert '<SupportAssets VALUE="/Runtime/Support/WEBSOUL_24156031_Road_Trip_Poses_for_Genesis_9.dsx">' in support
        assert f'<SupportAsset VALUE="/{converted_pose.removeprefix("Content/")}"/>' in support
        assert '<SupportAsset VALUE="/Runtime/Support/WEBSOUL_24156031_Road_Trip_Poses_for_Genesis_9.jpg"/>' in support
        assert "queueDBMetaFile" in support_script


def _require_road_trip_samples() -> None:
    if not ROAD_TRIP_ZIP.exists() or not ROAD_TRIP_G9_PATH.exists():
        pytest.skip("Road Trip pose converter calibration samples are local-only")


def _load_road_trip_g8_pose() -> dict:
    with ZipFile(ROAD_TRIP_ZIP) as archive:
        raw = archive.read(ROAD_TRIP_G8_PATH)
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


def _meaningful_animation_map(pose: dict) -> dict[tuple[str, str, str], float]:
    values = {}
    for animation in pose.get("scene", {}).get("animations", []):
        parsed = _parse_animation_url(animation.get("url", ""))
        keys = animation.get("keys", [])
        if parsed is None or not keys or len(keys[0]) < 2:
            continue
        value = float(keys[0][1])
        bone, group, axis = parsed
        if group == "scale" and abs(value - 1.0) < 0.000001:
            continue
        if abs(value) < 0.000001:
            continue
        values[(bone, group, axis)] = value
    return values


def _parse_animation_url(url: str) -> tuple[str, str, str] | None:
    prefix = "name://@selection/"
    marker = ":?"
    suffix = "/value"
    if not url.startswith(prefix) or marker not in url or not url.endswith(suffix):
        return None
    bone, channel = url[len(prefix) : -len(suffix)].split(marker, 1)
    parts = channel.split("/")
    if len(parts) != 2:
        return None
    return bone, parts[0], parts[1]
