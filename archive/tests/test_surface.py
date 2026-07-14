import math

from horncad.profile import derive_config
from horncad.surface import (
    corner_anchor_angles,
    generate_inside_surface,
    inside_surface_triangles,
    mouth_area,
    equivalent_round_reference_values,
    plotted_target_area_normalizer,
    rounded_rectangle_area,
    rounded_rectangle_boundary_distance,
    radial_sample_angles,
    snap_cardinal_angles,
    superellipse_surface_triangles,
    superellipse_boundary_distance,
    _superellipse_axis_detail_angles,
    _superellipse_xy,
    write_inside_surface_stl,
    write_superellipse_surface_stl,
    _superellipse_scope_angles,
    _superellipse_power_at_fraction,
)
from tests.helpers import (
    ANGULAR_SEGMENTS,
    LENGTH_MAX,
    MOUTH_HEIGHT,
    MOUTH_SAG,
    MOUTH_WIDTH,
    sample_project_config,
)


def test_generate_inside_surface_has_radial_curves_sections_and_area_fit():
    config = sample_project_config()

    result = generate_inside_surface(config)

    assert len(result.radial_curves) == config["resolution"]["angular_segments"]
    assert len(result.sections) == config["resolution"]["length_segments"] + 1
    expected_shared_length = LENGTH_MAX - MOUTH_SAG
    assert result.shared_section_length == expected_shared_length
    assert result.sections[-1].z_ref == expected_shared_length
    assert abs(result.radial_curves[0].boundary_x - MOUTH_WIDTH / 2.0) < 1e-6
    assert abs(result.radial_curves[ANGULAR_SEGMENTS // 4].boundary_y - MOUTH_HEIGHT / 2.0) < 1e-6
    assert 0.0 < result.area_fit.score <= 1.0
    assert result.area_fit.rms_percent_error >= 0.0
    assert result.area_fit.max_abs_percent_error >= result.area_fit.rms_percent_error
    assert result.issues == []


def test_inside_surface_stl_uses_existing_sampling_resolution(tmp_path):
    config = sample_project_config()
    config["outputs"]["scope"] = "quarter"
    result = generate_inside_surface(config)

    triangles = inside_surface_triangles(config, result)
    path = tmp_path / "inside_surface.stl"
    write_inside_surface_stl(config, result, path)

    scoped_curve_count = sum(1 for curve in result.radial_curves if 0.0 <= curve.p_deg <= 90.0)
    expected_triangles = (len(result.sections) - 1) * (scoped_curve_count - 1) * 2
    assert len(triangles) == expected_triangles
    text = path.read_text(encoding="ascii")
    assert text.startswith("solid inside_surface\n")
    assert text.count("facet normal") == expected_triangles


def test_superellipse_surface_stl_uses_hv_profiles_and_scope(tmp_path):
    config = sample_project_config()
    config["outputs"]["scope"] = "quarter"
    path = tmp_path / "superellipse_surface.stl"

    triangles = superellipse_surface_triangles(config)
    write_superellipse_surface_stl(config, path)

    scoped_angle_count = len(_superellipse_scope_angles(config, derive_config(config)))
    expected_triangles = config["resolution"]["length_segments"] * (scoped_angle_count - 1) * 2
    assert len(triangles) == expected_triangles
    text = path.read_text(encoding="ascii")
    assert text.startswith("solid superellipse_surface\n")
    assert text.count("facet normal") == expected_triangles


def test_superellipse_axis_detail_angles_resolve_flat_mouth_edge():
    angles = _superellipse_axis_detail_angles(96, 20.0)
    near_top = [angle for angle in angles if math.radians(80.0) <= angle <= math.pi / 2.0]
    near_right = [angle for angle in angles if 0.0 <= angle <= math.radians(10.0)]

    assert len(near_top) > 8
    assert len(near_right) > 8
    assert any(abs(angle - math.pi / 2.0) < 1e-9 for angle in angles)


def test_superellipse_cardinal_points_are_exact_for_high_power():
    assert _superellipse_xy(210.0, 97.5, 20.0, 0.0) == (210.0, 0.0)
    assert _superellipse_xy(210.0, 97.5, 20.0, math.pi / 2.0) == (0.0, 97.5)


def test_superellipse_power_uses_fractional_morph_schedule():
    config = sample_project_config()
    config["morph"]["rate"]["seed"] = 0.25

    start_power = _superellipse_power_at_fraction(config, 0.0)
    middle_power = _superellipse_power_at_fraction(config, 0.125)
    complete_power = _superellipse_power_at_fraction(config, 0.25)
    later_power = _superellipse_power_at_fraction(config, 0.5)

    assert start_power == 2.0
    assert 2.0 < middle_power < complete_power
    assert complete_power == later_power


def test_section_sampling_is_adaptive_along_z():
    config = sample_project_config()
    result = generate_inside_surface(config)

    intervals = [
        result.sections[index + 1].z_ref - result.sections[index].z_ref
        for index in range(len(result.sections) - 1)
    ]
    assert min(intervals) < max(intervals)


def test_radial_curve_sampling_is_adaptive_around_p():
    config = sample_project_config()
    result = generate_inside_surface(config)

    angles = [math.radians(curve.p_deg) for curve in result.radial_curves]
    intervals = [
        (angles[(index + 1) % len(angles)] - angles[index]) % (2.0 * math.pi)
        for index in range(len(angles))
    ]
    assert min(intervals) < max(intervals)


def test_radial_curve_sampling_includes_exact_horizontal_and_vertical_axes():
    config = sample_project_config()
    derived = derive_config(config)

    angles = radial_sample_angles(config, derived)

    assert 0.0 in angles
    assert math.pi / 2.0 in angles
    assert math.pi in angles
    assert 3.0 * math.pi / 2.0 in angles
    assert snap_cardinal_angles([math.pi / 2.0 + 1e-12]) == [math.pi / 2.0]


def test_rounded_rectangle_sampling_includes_corner_anchor_profiles():
    config = sample_project_config()
    config["mouth"]["shape"] = {"type": "rectangle", "shape_power": 6.0, "corner_radius": 4.0}
    derived = derive_config(config)

    anchors = corner_anchor_angles(config, derived)
    angles = radial_sample_angles(config, derived)

    assert len(anchors) == 5
    assert len(angles) == config["resolution"]["angular_segments"]
    assert all(any(abs(angle - anchor) < 1e-12 for angle in angles) for anchor in anchors)
    assert anchors == sorted(anchors)


def test_plotted_target_area_normalizer_uses_final_plotted_target():
    config = sample_project_config()
    result = generate_inside_surface(config)

    assert plotted_target_area_normalizer(result.sections) == result.sections[-1].target_area


def test_equivalent_round_reference_uses_polar_area_weighting():
    config = sample_project_config()
    derived = derive_config(config)

    reference = equivalent_round_reference_values(config, derived)

    simple_mean = (
        config["profiles"]["coverage"]["horizontal"]
        + config["profiles"]["coverage"]["vertical"]
    ) / 2.0
    assert reference.coverage_deg > simple_mean
    assert reference.coverage_deg < config["profiles"]["coverage"]["horizontal"]


def test_exact_rectangle_boundary_has_flat_sides():
    config = sample_project_config()
    config["mouth"]["shape"] = {"type": "rectangle", "shape_power": 6.0, "corner_radius": None}
    derived = derive_config(config)

    for degrees in (0.0, 15.0):
        distance = superellipse_boundary_distance(config, derived, math.radians(degrees))
        x = distance * math.cos(math.radians(degrees))
        assert abs(x - MOUTH_WIDTH / 2.0) < 1e-6


def test_exact_rounded_rectangle_boundary_and_area():
    corner_radius = 20.0
    assert rounded_rectangle_area(MOUTH_WIDTH, MOUTH_HEIGHT, corner_radius) == (
        MOUTH_WIDTH * MOUTH_HEIGHT - (4.0 - math.pi) * corner_radius**2
    )

    config = sample_project_config()
    config["mouth"]["shape"] = {"type": "rounded_rectangle", "shape_power": 6.0, "corner_radius": corner_radius}
    derived = derive_config(config)

    half_width = MOUTH_WIDTH / 2.0
    half_height = MOUTH_HEIGHT / 2.0
    assert mouth_area(config, derived) == rounded_rectangle_area(MOUTH_WIDTH, MOUTH_HEIGHT, corner_radius)
    assert abs(rounded_rectangle_boundary_distance(half_width, half_height, corner_radius, 0.0) - half_width) < 1e-6
    assert rounded_rectangle_boundary_distance(half_width, half_height, corner_radius, math.radians(30.0)) < (
        half_width / math.cos(math.radians(30.0))
    )

