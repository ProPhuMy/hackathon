import numpy as np
import pytest
from src.identity.gallery import Gallery


def test_gallery_roundtrip_model_binding_and_deliberate_removal(tmp_path):
    path = tmp_path / 'gallery.json'
    gallery = Gallery(path, 'model-a')
    gallery.enroll('p_01', [[1., 0.]] * 10)
    assert Gallery(path, 'model-a').scores([1., 0.]) == {'p_01': 1.}
    with pytest.raises(ValueError):
        gallery.enroll('p_01', [[1., 0.]] * 10)
    with pytest.raises(ValueError):
        Gallery(path, 'model-b')
    gallery.remove('p_01')
    assert Gallery(path, 'model-a').people == {}


def test_enrollment_rejects_bad_ids_and_insufficient_samples(tmp_path):
    gallery = Gallery(tmp_path / 'g.json', 'a')
    for person, samples in [('../bad', [[1., 0.]] * 10), ('p_01', [[1., 0.]])]:
        with pytest.raises(ValueError):
            gallery.enroll(person, samples)


def test_reenrollment_invalidates_old_policy_even_with_identical_vectors(tmp_path):
    gallery = Gallery(tmp_path / 'gallery.json', 'a')
    gallery.enroll('p_01', [[1., 0.]] * 10)
    old = gallery.fingerprint
    gallery.remove('p_01')
    gallery.enroll('p_01', [[1., 0.]] * 10)
    assert gallery.fingerprint != old


def test_gallery_fingerprint_stays_stable_for_real_dimension_vectors(tmp_path):
    gallery = Gallery(tmp_path / 'gallery.json', 'a')
    vector = np.random.default_rng(2).normal(size=512)
    gallery.enroll('p_01', [vector] * 10)
    assert gallery.fingerprint == Gallery(gallery.path, 'a').fingerprint


def test_dual_gallery_enrollment_scoring_and_removal(tmp_path):
    from src.identity.gallery import DualGallery
    arc_path = tmp_path / 'arcface.json'
    ada_path = tmp_path / 'adaface.json'
    g_arc = Gallery(arc_path, 'arc-v1')
    g_ada = Gallery(ada_path, 'ada-v1')
    dual = DualGallery(g_arc, g_ada)

    assert dual.people == set()
    dual.enroll('p_01', [[1., 0.]] * 10, [[0., 1.]] * 10)
    assert dual.people == {'p_01'}
    
    arc_scores, ada_scores = dual.scores([1., 0.], [0., 1.])
    assert np.isclose(arc_scores['p_01'], 1.)
    assert np.isclose(ada_scores['p_01'], 1.)

    # Mismatched model/identity check
    g_ada.enroll('p_02', [[0., 1.]] * 10)
    with pytest.raises(ValueError, match='DualGallery identities mismatch'):
        DualGallery(Gallery(arc_path, 'arc-v1'), g_ada)

    # Removal removes from both
    g_ada.remove('p_02')
    dual3 = DualGallery(Gallery(arc_path, 'arc-v1'), Gallery(ada_path, 'ada-v1'))
    dual3.remove('p_01')
    assert dual3.people == set()

